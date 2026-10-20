"""Catalogue coordinator and background sync manager."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    AUTO_SYNC_HOUR,
    AUTO_SYNC_OFF,
    AUTO_SYNC_WEEKDAY,
    AUTO_SYNC_WEEKLY,
    CATALOGUE_CHECK_INTERVAL,
    CATALOGUE_MAX_AGE,
    CONF_LIBRARY_PATH,
    CONF_PENDING_MOVE_FROM,
    DEFAULT_OPTIONS,
    DOMAIN,
    INDEX_SAVE_DELAY,
    ISSUE_LIBRARY_NOT_WRITABLE,
    ISSUE_LOW_DISK_SPACE,
    ISSUE_ORPHANED_FILES,
    ISSUE_SELECTION_MISSING,
    OPT_AUTO_SYNC,
    OPT_BANDWIDTH_LIMIT,
    OPT_MAX_PARALLEL,
    OPT_NAMES_LANGUAGE,
    OPT_NUMBER_SEPARATOR,
    OPT_REDOWNLOAD_CHANGED,
    OPT_TITLE_FORMAT,
    REPO_URL,
    STORAGE_KEY_CATALOGUE,
    STORAGE_KEY_INDEX,
    STORAGE_KEY_SYNC_STATE,
    STORAGE_VERSION,
)
from .helpers import library_root_of, naming_options_of, selection_title, selections_of
from .lib.api import Mp3QuranClient, Mp3QuranError
from .lib.downloader import Downloader
from .lib.library import LibraryIndex, build_plan, desired_tracks
from .lib.models import (
    Catalogue,
    JobKind,
    Selection,
    SyncProgress,
    SyncResult,
    SyncState,
)
from .lib.sync import InsufficientSpace, LibraryNotWritable, SyncEngine

_LOGGER = logging.getLogger(__name__)

type TilawaConfigEntry = ConfigEntry[TilawaRuntimeData]


@dataclass
class TilawaRuntimeData:
    """Objects kept on ``entry.runtime_data``."""

    client: Mp3QuranClient
    catalogue: TilawaCatalogueCoordinator
    sync: TilawaSyncManager
    version: str


@dataclass(frozen=True, slots=True)
class LibraryStats:
    """Numbers shown by the diagnostic sensors."""

    files: int
    bytes: int
    reciters: int


def _gb(value: int) -> str:
    return f"{value / 1_000_000_000:.1f} GB"


class TilawaCatalogueCoordinator(DataUpdateCoordinator[Catalogue]):
    """Keep the mp3quran catalogue fresh (weekly) and watch API connectivity (daily).

    The catalogue is cached in ``.storage`` so a restart never needs the network, and
    a failed refresh keeps serving the cache while ``api_available`` turns False.
    """

    config_entry: TilawaConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: TilawaConfigEntry, client: Mp3QuranClient
    ) -> None:
        """Create the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} catalogue",
            update_interval=CATALOGUE_CHECK_INTERVAL,
        )
        self._client = client
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, STORAGE_KEY_CATALOGUE
        )
        self._cached: Catalogue | None = None
        self.api_available = True

    async def _async_setup(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        try:
            self._cached = Catalogue.from_dict(data)
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Ignoring unreadable catalogue cache: %s", err)

    @staticmethod
    def _is_fresh(catalogue: Catalogue) -> bool:
        return dt_util.utcnow() - catalogue.fetched_at < CATALOGUE_MAX_AGE

    async def _async_update_data(self) -> Catalogue:
        current = self.data or self._cached
        if current is not None and self._is_fresh(current):
            try:
                await self._client.async_ping()
            except Mp3QuranError as err:
                self._set_api_available(False, err)
            else:
                self._set_api_available(True)
            return current
        try:
            catalogue = await self._client.async_fetch_catalogue()
        except Mp3QuranError as err:
            self._set_api_available(False, err)
            if current is not None:
                return current
            raise UpdateFailed(f"Cannot fetch the mp3quran catalogue: {err}") from err
        self._set_api_available(True)
        self._cached = catalogue
        await self._store.async_save(catalogue.to_dict())
        self.check_selections(catalogue)
        return catalogue

    @callback
    def _set_api_available(self, available: bool, err: Exception | None = None) -> None:
        if available and not self.api_available:
            _LOGGER.info("Connection to mp3quran.net restored")
        elif not available and self.api_available:
            _LOGGER.warning(
                "mp3quran.net is unreachable, using the cached catalogue: %s", err
            )
        self.api_available = available

    @callback
    def check_selections(self, catalogue: Catalogue) -> None:
        """Raise or clear repairs for selections the catalogue no longer lists."""
        language = naming_options_of(self.config_entry).names_language
        for selection in selections_of(self.config_entry):
            issue_id = f"{ISSUE_SELECTION_MISSING}_{selection.key}"
            moshaf = catalogue.moshafs.get(selection.moshaf_id)
            if moshaf is None or moshaf.reciter_id != selection.reciter_id:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_SELECTION_MISSING,
                    translation_placeholders={
                        "selection": selection_title(catalogue, selection, language)
                    },
                    data={"selection_key": selection.key},
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def async_remove_cache(self) -> None:
        """Delete the cached catalogue (on entry removal)."""
        await self._store.async_remove()


class TilawaSyncManager:
    """Own the sync engine, run jobs in the background and persist their state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TilawaConfigEntry,
        client: Mp3QuranClient,
        catalogue: TilawaCatalogueCoordinator,
    ) -> None:
        """Create the manager; call ``async_load`` before use."""
        self.hass = hass
        self.entry = entry
        self._client = client
        self._catalogue = catalogue
        self._index_store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, STORAGE_KEY_INDEX
        )
        self._state_store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, STORAGE_KEY_SYNC_STATE
        )
        self.index = LibraryIndex()
        self.engine: SyncEngine | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._task: asyncio.Task[None] | None = None
        self._cancel = asyncio.Event()
        self._queue: list[tuple[JobKind, Selection | None]] = []
        self._shutting_down = False
        self._resume: JobKind | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_started: CALLBACK_TYPE | None = None
        self._snapshot_options: dict[str, Any] = {}
        self._snapshot_selections: dict[str, Selection] = {}
        self.last_success: datetime | None = None
        self.last_result: SyncResult | None = None
        self.errors: list[str] = []

    # ---------------------------------------------------------------- lifecycle

    async def async_load(self) -> None:
        """Load persisted index and job state, then build the engine."""
        if index_data := await self._index_store.async_load():
            try:
                self.index = LibraryIndex.from_dict(index_data)
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.warning("Ignoring unreadable library index: %s", err)
        state = await self._state_store.async_load() or {}
        if last := state.get("last_success"):
            self.last_success = datetime.fromisoformat(last)
        if result := state.get("last_result"):
            try:
                self.last_result = SyncResult.from_dict(result)
            except KeyError, TypeError, ValueError:
                self.last_result = None
        self.errors = list(state.get("errors", []))
        if active := state.get("active_job"):
            try:
                self._resume = JobKind(active["kind"])
            except KeyError, ValueError:
                self._resume = None

        pending_from = self.entry.data.get(CONF_PENDING_MOVE_FROM)
        root = Path(pending_from) if pending_from else library_root_of(self.entry)
        self.engine = SyncEngine(
            client=self._client,
            downloader=self._make_downloader(),
            root=root,
            index=self.index,
            run_blocking=self._run_blocking,
            on_progress=self._on_progress,
            on_index_changed=self._async_index_changed,
        )
        self._take_snapshot()

    @callback
    def async_start(self) -> None:
        """Arm the schedule and resume pending work once Home Assistant is running."""
        self._arm_auto_sync()
        if self.hass.is_running:
            self.entry.async_create_background_task(
                self.hass, self._async_on_started(), name=f"{DOMAIN} startup"
            )
        else:
            self._unsub_started = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_on_started_event
            )

    async def _async_on_started_event(self, _event: Event) -> None:
        self._unsub_started = None
        await self._async_on_started()

    async def _async_on_started(self) -> None:
        if self.entry.data.get(CONF_PENDING_MOVE_FROM):
            await self._async_request(JobKind.MOVE, None)
        elif self._resume is not None:
            _LOGGER.info("Resuming interrupted %s job", self._resume.value)
            kind, self._resume = self._resume, None
            await self._async_request(kind, None)

    async def async_shutdown(self) -> None:
        """Stop timers and the running job, keeping it marked for resume."""
        self._shutting_down = True
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_started:
            self._unsub_started()
            self._unsub_started = None
        if self._task and not self._task.done():
            self._queue.clear()
            self._cancel.set()
            try:
                async with asyncio.timeout(30):
                    await self._task
            except TimeoutError, asyncio.CancelledError:
                self._task.cancel()

    async def async_remove_storage(self) -> None:
        """Delete persisted index and state (on entry removal)."""
        await self._index_store.async_remove()
        await self._state_store.async_remove()

    # ------------------------------------------------------------ collaborators

    def _run_blocking[T](self, func: Callable[..., T], /, *args: Any) -> Awaitable[T]:
        return self.hass.async_add_executor_job(func, *args)

    def _make_downloader(self) -> Downloader:
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        return Downloader(
            async_get_clientsession(self.hass),
            max_parallel=int(options[OPT_MAX_PARALLEL]),
            bandwidth_limit_kbps=int(options[OPT_BANDWIDTH_LIMIT]),
            user_agent=f"Tilawa/{self.entry.runtime_data.version} (+{REPO_URL})"
            if hasattr(self.entry, "runtime_data")
            else f"Tilawa (+{REPO_URL})",
            run_blocking=self._run_blocking,
        )

    # ---------------------------------------------------------------- listeners

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register an entity callback; returns the unsubscribe function."""
        self._listeners.append(update_callback)

        @callback
        def _remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove

    @callback
    def _notify(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    def _on_progress(self, _progress: SyncProgress) -> None:
        self._notify()

    async def _async_index_changed(self) -> None:
        self._index_store.async_delay_save(self.index.to_dict, INDEX_SAVE_DELAY)
        self._notify()

    # ------------------------------------------------------------------- state

    @property
    def progress(self) -> SyncProgress:
        """Return the live progress of the current or last job."""
        return self.engine.progress if self.engine else SyncProgress()

    @property
    def state(self) -> SyncState:
        """Return the current state."""
        return self.progress.state

    @property
    def is_running(self) -> bool:
        """Return True while a job task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def stats(self) -> LibraryStats:
        """Return the numbers for the diagnostic sensors."""
        return LibraryStats(
            files=len(self.index),
            bytes=self.index.total_bytes,
            reciters=len({s.reciter_id for s in selections_of(self.entry)}),
        )

    def _take_snapshot(self) -> None:
        self._snapshot_options = dict(self.entry.options)
        self._snapshot_selections = {s.key: s for s in selections_of(self.entry)}

    # ------------------------------------------------------------------ requests

    async def async_request_sync(self, selection: Selection | None = None) -> None:
        """Queue a sync (optionally for one selection) and start it if idle."""
        await self._async_request(JobKind.SYNC, selection)

    async def async_request_retag(self) -> None:
        """Queue a retag job."""
        await self._async_request(JobKind.RETAG, None)

    async def _async_request(self, kind: JobKind, selection: Selection | None) -> None:
        request = (kind, selection)
        if request not in self._queue:
            self._queue.append(request)
        if not self.is_running:
            self._task = self.entry.async_create_background_task(
                self.hass, self._async_run_queue(), name=f"{DOMAIN} jobs"
            )
        self._notify()

    async def async_cancel(self) -> None:
        """Cancel the running job and drop queued ones."""
        self._queue.clear()
        self._cancel.set()
        self._notify()

    async def async_delete_selection_files(self, selection_key: str) -> int:
        """Delete the files of a selection; refuses while a job runs."""
        if self.is_running:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="busy")
        assert self.engine is not None
        deleted = await self.engine.async_delete_selection(selection_key)
        ir.async_delete_issue(
            self.hass, DOMAIN, f"{ISSUE_ORPHANED_FILES}_{selection_key}"
        )
        self._notify()
        return deleted

    # ------------------------------------------------------------- entry updates

    async def async_handle_entry_update(self) -> None:
        """React to option or subentry changes without reloading the entry."""
        options = {**DEFAULT_OPTIONS, **self.entry.options}
        previous = {**DEFAULT_OPTIONS, **self._snapshot_options}
        selections = {s.key: s for s in selections_of(self.entry)}
        previous_selections = self._snapshot_selections
        self._take_snapshot()

        naming_changed = any(
            options[key] != previous[key]
            for key in (OPT_NAMES_LANGUAGE, OPT_TITLE_FORMAT, OPT_NUMBER_SEPARATOR)
        )
        if options[OPT_AUTO_SYNC] != previous[OPT_AUTO_SYNC]:
            self._arm_auto_sync()
        for key in previous_selections.keys() - selections.keys():
            self._raise_orphan_issue(key, previous_selections[key])
        added_or_widened = [
            selection
            for key, selection in selections.items()
            if key not in previous_selections
            or previous_selections[key].surahs != selection.surahs
        ]
        if self._catalogue.data is not None:
            self._catalogue.check_selections(self._catalogue.data)
        if naming_changed:
            await self.async_request_retag()
        if added_or_widened:
            await self.async_request_sync()
        self._notify()

    @callback
    def _raise_orphan_issue(self, selection_key: str, selection: Selection) -> None:
        issue_id = f"{ISSUE_ORPHANED_FILES}_{selection_key}"
        keys = self.index.keys_for_selection(selection_key)
        if not keys:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        catalogue = self._catalogue.data
        title = (
            selection_title(
                catalogue, selection, naming_options_of(self.entry).names_language
            )
            if catalogue is not None
            else selection_key
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ORPHANED_FILES,
            translation_placeholders={"selection": title, "count": str(len(keys))},
            data={"selection_key": selection_key},
        )

    # ----------------------------------------------------------------- schedule

    @callback
    def _arm_auto_sync(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        mode = self.entry.options.get(OPT_AUTO_SYNC, AUTO_SYNC_OFF)
        if mode == AUTO_SYNC_OFF:
            return
        self._unsub_timer = async_track_time_change(
            self.hass, self._async_auto_sync, hour=AUTO_SYNC_HOUR, minute=0, second=0
        )

    async def _async_auto_sync(self, now: datetime) -> None:
        mode = self.entry.options.get(OPT_AUTO_SYNC, AUTO_SYNC_OFF)
        if mode == AUTO_SYNC_WEEKLY and now.weekday() != AUTO_SYNC_WEEKDAY:
            return
        _LOGGER.debug("Scheduled %s sync", mode)
        await self.async_request_sync()

    # --------------------------------------------------------------------- jobs

    async def _async_run_queue(self) -> None:
        try:
            while self._queue:
                kind, selection = self._queue.pop(0)
                self._cancel = asyncio.Event()
                await self._async_run_job(kind, selection)
                if self._cancel.is_set():
                    self._queue.clear()
        finally:
            self._task = None
            self._notify()

    async def _async_run_job(self, kind: JobKind, selection: Selection | None) -> None:
        engine = self.engine
        assert engine is not None
        engine.downloader = self._make_downloader()
        await self._async_persist_state(active=(kind, selection))
        result: SyncResult | None = None
        try:
            if kind is JobKind.SYNC:
                result = await self._async_sync(engine, selection)
            elif kind is JobKind.RETAG:
                result = await engine.async_retag(
                    self._catalogue.data,
                    selections_of(self.entry),
                    naming_options_of(self.entry),
                    self._cancel,
                )
            else:
                result = await self._async_move(engine)
        except InsufficientSpace as err:
            self._fail(engine, f"Not enough free space: {err}")
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_LOW_DISK_SPACE,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_LOW_DISK_SPACE,
                translation_placeholders={
                    "needed": _gb(err.needed),
                    "free": _gb(err.free),
                },
            )
        except LibraryNotWritable as err:
            self._fail(engine, f"Library folder not writable: {err}")
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_LIBRARY_NOT_WRITABLE,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_LIBRARY_NOT_WRITABLE,
                translation_placeholders={"path": str(engine.root)},
            )
        except Exception as err:
            _LOGGER.exception("Unexpected error in %s job", kind.value)
            self._fail(engine, f"{type(err).__name__}: {err}")
        else:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_LOW_DISK_SPACE)
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_LIBRARY_NOT_WRITABLE)
            self.last_result = result
            self.errors = list(result.errors)
            if result.success and kind is JobKind.SYNC:
                self.last_success = dt_util.utcnow()
            _LOGGER.info(
                "%s job finished: %d processed, %d failed%s",
                kind.value.capitalize(),
                result.processed,
                result.failed,
                " (cancelled)" if result.cancelled else "",
            )
        finally:
            keep_active = self._shutting_down and not self._cancel_was_user()
            await self._async_persist_state(
                active=(kind, selection) if keep_active else None
            )
            self._notify()

    def _cancel_was_user(self) -> bool:
        # During shutdown the cancel event is set by async_shutdown, not the user.
        return not self._shutting_down

    @callback
    def _fail(self, engine: SyncEngine, message: str) -> None:
        engine.progress.state = SyncState.ERROR
        engine.progress.error = message
        self.errors = [message, *self.errors][:20]
        _LOGGER.error("%s", message)

    async def _async_sync(
        self, engine: SyncEngine, selection: Selection | None
    ) -> SyncResult:
        catalogue = self._catalogue.data
        selections = selections_of(self.entry)
        if selection is not None:
            selections = [s for s in selections if s.key == selection.key]
        options = naming_options_of(self.entry)
        redownload = bool(self.entry.options.get(OPT_REDOWNLOAD_CHANGED, False))
        existing = await engine.async_existing_keys()
        remote = None
        if redownload:
            tracks, _ = desired_tracks(catalogue, selections, options)
            remote = await engine.async_head_many(
                spec for key, spec in tracks.items() if key in existing
            )
        plan = build_plan(
            catalogue,
            selections,
            options,
            self.index,
            existing_keys=existing,
            redownload_changed=redownload,
            remote=remote,
        )
        for missing in plan.missing_selections:
            _LOGGER.warning(
                "Selection %s is not in the catalogue; skipping", missing.key
            )
        await engine.async_estimate(plan)
        self._notify()
        return await engine.async_run(plan, self._cancel)

    async def _async_move(self, engine: SyncEngine) -> SyncResult:
        new_root = Path(self.entry.data[CONF_LIBRARY_PATH])
        result = await engine.async_move_root(new_root, self._cancel)
        if result.success:
            data = {
                k: v for k, v in self.entry.data.items() if k != CONF_PENDING_MOVE_FROM
            }
            self.hass.config_entries.async_update_entry(self.entry, data=data)
        return result

    async def _async_persist_state(
        self, *, active: tuple[JobKind, Selection | None] | None
    ) -> None:
        await self._state_store.async_save(
            {
                "active_job": None
                if active is None
                else {
                    "kind": active[0].value,
                    "selection": active[1].to_dict() if active[1] else None,
                },
                "last_success": self.last_success.isoformat()
                if self.last_success
                else None,
                "last_result": self.last_result.to_dict() if self.last_result else None,
                "errors": self.errors[:20],
            }
        )
