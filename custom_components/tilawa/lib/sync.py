"""The sync engine: runs plans, retags, moves and deletes. Pure Python.

Blocking file operations are small functions handed to ``run_blocking`` so that
Home Assistant can route them through its executor.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
import logging
from pathlib import Path, PurePosixPath
import shutil

from .api import Mp3QuranClient, Mp3QuranError
from .downloader import DownloadCancelled, Downloader, RunBlocking, run_in_thread
from .library import LibraryIndex, desired_tracks
from .models import (
    Catalogue,
    IndexedFile,
    JobKind,
    NamingOptions,
    RemoteFile,
    Selection,
    SyncPlan,
    SyncProgress,
    SyncResult,
    SyncState,
    TrackIdentity,
    TrackSpec,
    TrackTags,
    selection_key_of_track,
)
from .tagger import read_identity, write_tags

_LOGGER = logging.getLogger(__name__)

PART_SUFFIX = ".part"
MAX_RECORDED_ERRORS = 20
PROGRESS_BYTES_STEP = 1024 * 1024
FREE_SPACE_MARGIN = 0.05
FREE_SPACE_RESERVE = 256 * 1024 * 1024

type ProgressCallback = Callable[[SyncProgress], None]
type IndexChangedCallback = Callable[[], Awaitable[None]]


class InsufficientSpace(Exception):
    """Not enough free space for the planned downloads."""

    def __init__(self, needed: int, free: int) -> None:
        """Record the numbers for the repair issue."""
        super().__init__(f"need {needed} bytes, {free} free")
        self.needed = needed
        self.free = free


class LibraryNotWritable(Exception):
    """The library folder cannot be written to."""


def to_path(root: Path, relative_path: str) -> Path:
    """Join a stored POSIX-style relative path onto the library root."""
    return root.joinpath(*PurePosixPath(relative_path).parts)


def check_free_space(root: Path, needed: int) -> None:
    """Raise :class:`InsufficientSpace` unless ``needed`` bytes (plus margin) fit."""
    free = shutil.disk_usage(root).free
    required = int(needed * (1 + FREE_SPACE_MARGIN)) + FREE_SPACE_RESERVE
    if free < required:
        raise InsufficientSpace(required, free)


def check_writable(root: Path) -> None:
    """Raise :class:`LibraryNotWritable` unless ``root`` exists and accepts files."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".tilawa-write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as err:
        raise LibraryNotWritable(f"{root}: {err}") from err


def prune_empty_dirs(start: Path, root: Path) -> None:
    """Remove empty directories from ``start`` up to (not including) ``root``."""
    current = start
    while current != root and current.is_relative_to(root):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


class SyncEngine:
    """Execute library jobs against one root folder and one index."""

    def __init__(
        self,
        *,
        client: Mp3QuranClient,
        downloader: Downloader,
        root: Path,
        index: LibraryIndex,
        run_blocking: RunBlocking = run_in_thread,
        on_progress: ProgressCallback | None = None,
        on_index_changed: IndexChangedCallback | None = None,
        head_concurrency: int = 4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Wire the engine to its collaborators."""
        self._client = client
        self.downloader = downloader
        self.root = root
        self.index = index
        self._run_blocking = run_blocking
        self._on_progress = on_progress
        self._on_index_changed = on_index_changed
        self._head_concurrency = head_concurrency
        self._now = now
        self.progress = SyncProgress()
        self._last_emitted_bytes = 0

    # ------------------------------------------------------------------ helpers

    def _emit(self) -> None:
        if self._on_progress is not None:
            self._on_progress(self.progress)

    def _on_bytes(self, count: int) -> None:
        self.progress.bytes_done += count
        if self.progress.bytes_done - self._last_emitted_bytes >= PROGRESS_BYTES_STEP:
            self._last_emitted_bytes = self.progress.bytes_done
            self._emit()

    async def _index_changed(self) -> None:
        if self._on_index_changed is not None:
            await self._on_index_changed()

    def _start(
        self, kind: JobKind, state: SyncState, total: int, bytes_total: int
    ) -> None:
        self.progress = SyncProgress(
            state=state,
            kind=kind,
            total=total,
            bytes_total=bytes_total,
            started_at=self._now(),
        )
        self._last_emitted_bytes = 0
        self._emit()

    def _finish(
        self,
        kind: JobKind,
        cancelled: bool,
        errors: list[str],
        bytes_downloaded: int = 0,
    ) -> SyncResult:
        progress = self.progress
        started = progress.started_at or self._now()
        progress.state = SyncState.ERROR if progress.failed else SyncState.IDLE
        progress.error = errors[0] if errors else None
        progress.current_key = None
        self._emit()
        return SyncResult(
            kind=kind,
            started_at=started,
            finished_at=self._now(),
            processed=progress.done,
            failed=progress.failed,
            cancelled=cancelled,
            bytes_downloaded=bytes_downloaded,
            errors=tuple(errors[:MAX_RECORDED_ERRORS]),
        )

    # ------------------------------------------------------------- inspection

    async def async_existing_keys(self) -> set[str]:
        """Return the indexed keys whose file is really on disk."""
        return await self._run_blocking(self._existing_keys)

    def _existing_keys(self) -> set[str]:
        return {
            key
            for key, file in self.index.files.items()
            if to_path(self.root, file.relative_path).is_file()
        }

    async def async_check_writable(self) -> None:
        """Raise :class:`LibraryNotWritable` if the root cannot be written."""
        await self._run_blocking(check_writable, self.root)

    async def async_head_many(
        self, specs: Iterable[TrackSpec]
    ) -> dict[str, RemoteFile]:
        """HEAD the given tracks with bounded concurrency; failures are skipped."""
        semaphore = asyncio.Semaphore(self._head_concurrency)
        results: dict[str, RemoteFile] = {}

        async def head(spec: TrackSpec) -> None:
            async with semaphore:
                try:
                    results[spec.key] = await self._client.async_head(spec.url)
                except Mp3QuranError as err:
                    _LOGGER.debug("HEAD %s failed: %s", spec.url, err)

        await asyncio.gather(*(head(spec) for spec in specs))
        return results

    async def async_estimate(self, plan: SyncPlan) -> int:
        """HEAD planned downloads not yet described, fill ``plan.remote``, return bytes."""
        missing = [spec for spec in plan.downloads if spec.key not in plan.remote]
        plan.remote.update(await self.async_head_many(missing))
        total = sum(
            plan.remote[spec.key].size or 0
            for spec in plan.downloads
            if spec.key in plan.remote
        )
        plan.estimated_bytes = total
        return total

    # ------------------------------------------------------------------- sync

    async def async_run(self, plan: SyncPlan, cancel: asyncio.Event) -> SyncResult:
        """Download everything in ``plan`` (retags included) and update the index."""
        self._start(
            JobKind.SYNC,
            SyncState.SYNCING,
            len(plan.downloads) + len(plan.retags),
            plan.estimated_bytes or 0,
        )
        errors: list[str] = []
        bytes_before = self.progress.bytes_done

        await self.async_check_writable()
        if plan.estimated_bytes:
            await self._run_blocking(check_free_space, self.root, plan.estimated_bytes)

        for indexed, spec in plan.retags:
            if cancel.is_set():
                break
            await self._retag_one(indexed, spec, errors)

        queue: asyncio.Queue[TrackSpec] = asyncio.Queue()
        for spec in plan.downloads:
            queue.put_nowait(spec)
        workers = [
            asyncio.create_task(self._download_worker(queue, plan, cancel, errors))
            for _ in range(
                min(self.downloader.max_parallel, max(1, len(plan.downloads)))
            )
        ]
        await asyncio.gather(*workers)
        await self._index_changed()
        return self._finish(
            JobKind.SYNC,
            cancel.is_set(),
            errors,
            bytes_downloaded=self.progress.bytes_done - bytes_before,
        )

    async def _download_worker(
        self,
        queue: asyncio.Queue[TrackSpec],
        plan: SyncPlan,
        cancel: asyncio.Event,
        errors: list[str],
    ) -> None:
        while not cancel.is_set():
            try:
                spec = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self.progress.current_key = spec.key
            try:
                await self._download_one(spec, plan.remote.get(spec.key), cancel)
            except DownloadCancelled:
                return
            except Exception as err:  # noqa: BLE001 - one bad file must not stop the job
                self.progress.failed += 1
                errors.append(f"{spec.key}: {err}")
                _LOGGER.warning(
                    "Failed to download %s (%s): %s", spec.key, spec.url, err
                )
            finally:
                self.progress.done += 1
                self._emit()

    async def _download_one(
        self, spec: TrackSpec, remote: RemoteFile | None, cancel: asyncio.Event
    ) -> None:
        final = to_path(self.root, spec.relative_path)
        part = final.with_name(final.name + PART_SUFFIX)
        result = await self.downloader.async_download(
            spec.url, part, expected=remote, on_progress=self._on_bytes, cancel=cancel
        )
        tags = replace(spec.tags, source_etag=result.etag)
        size = await self._run_blocking(_tag_and_publish, part, final, tags)
        self.index.add(
            IndexedFile(
                key=spec.key,
                relative_path=spec.relative_path,
                size=size,
                source_etag=result.etag,
                naming_fingerprint=spec.naming_fingerprint,
                downloaded_at=self._now(),
            )
        )
        await self._index_changed()

    # ------------------------------------------------------------------ retag

    async def async_retag(
        self,
        catalogue: Catalogue,
        selections: Sequence[Selection],
        options: NamingOptions,
        cancel: asyncio.Event,
    ) -> SyncResult:
        """Rewrite tags (and rename files) so they match ``options``."""
        desired, _ = desired_tracks(catalogue, selections, options)
        todo = [
            (indexed, desired[key])
            for key, indexed in self.index.files.items()
            if key in desired
            and (
                indexed.naming_fingerprint != desired[key].naming_fingerprint
                or indexed.relative_path != desired[key].relative_path
            )
        ]
        self._start(JobKind.RETAG, SyncState.RETAGGING, len(todo), 0)
        errors: list[str] = []
        for indexed, spec in todo:
            if cancel.is_set():
                break
            await self._retag_one(indexed, spec, errors)
        await self._index_changed()
        return self._finish(JobKind.RETAG, cancel.is_set(), errors)

    async def _retag_one(
        self, indexed: IndexedFile, spec: TrackSpec, errors: list[str]
    ) -> None:
        self.progress.current_key = spec.key
        try:
            size = await self._run_blocking(_retag_file, self.root, indexed, spec)
        except OSError as err:
            self.progress.failed += 1
            errors.append(f"{spec.key}: {err}")
            _LOGGER.warning("Failed to retag %s: %s", spec.key, err)
        else:
            if size is None:
                self.index.remove(indexed.key)
            else:
                self.index.add(
                    replace(
                        indexed,
                        relative_path=spec.relative_path,
                        size=size,
                        naming_fingerprint=spec.naming_fingerprint,
                    )
                )
        finally:
            self.progress.done += 1
            self._emit()

    # ------------------------------------------------------------------- move

    async def async_move_root(
        self, new_root: Path, cancel: asyncio.Event
    ) -> SyncResult:
        """Move every indexed file to ``new_root`` and switch the engine to it."""
        files = list(self.index)
        self._start(JobKind.MOVE, SyncState.MOVING, len(files), 0)
        errors: list[str] = []
        await self._run_blocking(check_writable, new_root)
        for file in files:
            if cancel.is_set():
                break
            self.progress.current_key = file.key
            try:
                await self._run_blocking(_move_file, self.root, new_root, file)
            except OSError as err:
                self.progress.failed += 1
                errors.append(f"{file.key}: {err}")
                _LOGGER.warning("Failed to move %s: %s", file.key, err)
            finally:
                self.progress.done += 1
                self._emit()
        if not errors and not cancel.is_set():
            self.root = new_root
        await self._index_changed()
        return self._finish(JobKind.MOVE, cancel.is_set(), errors)

    # ----------------------------------------------------------------- delete

    async def async_delete(self, keys: Sequence[str]) -> int:
        """Delete indexed files whose on-disk identity matches; return the count."""
        deleted = 0
        for key in keys:
            indexed = self.index.get(key)
            if indexed is None:
                continue
            removed = await self._run_blocking(_delete_file, self.root, indexed)
            if removed:
                deleted += 1
            self.index.remove(key)
        await self._index_changed()
        return deleted

    async def async_delete_selection(self, selection_key: str) -> int:
        """Delete every indexed file of one selection."""
        return await self.async_delete(self.index.keys_for_selection(selection_key))

    def orphan_keys(self, selections: Sequence[Selection]) -> list[str]:
        """Return indexed keys that no current selection covers."""
        wanted = {selection.key for selection in selections}
        return [
            key for key in self.index.files if selection_key_of_track(key) not in wanted
        ]

    # ------------------------------------------------------------------ adopt

    async def async_adopt(self) -> int:
        """Index files under the root that carry our tags but are unknown. Return count."""
        found = await self._run_blocking(_scan_tagged_files, self.root)
        adopted = 0
        for relative_path, identity, size in found:
            if identity.key in self.index:
                continue
            self.index.add(
                IndexedFile(
                    key=identity.key,
                    relative_path=relative_path,
                    size=size,
                    source_etag=identity.source_etag,
                    naming_fingerprint="",  # unknown: forces a retag check
                    downloaded_at=self._now(),
                )
            )
            adopted += 1
        if adopted:
            await self._index_changed()
        return adopted


# ------------------------------------------------------------- blocking parts


def _tag_and_publish(part: Path, final: Path, tags: TrackTags) -> int:
    write_tags(part, tags)
    size = part.stat().st_size
    part.replace(final)
    return size


def _retag_file(root: Path, indexed: IndexedFile, spec: TrackSpec) -> int | None:
    old = to_path(root, indexed.relative_path)
    new = to_path(root, spec.relative_path)
    if not old.is_file():
        return None
    if new != old:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.replace(new)
        prune_empty_dirs(old.parent, root)
    write_tags(new, replace(spec.tags, source_etag=indexed.source_etag))
    return new.stat().st_size


def _move_file(old_root: Path, new_root: Path, file: IndexedFile) -> None:
    src = to_path(old_root, file.relative_path)
    dst = to_path(new_root, file.relative_path)
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dst)
    except OSError:
        shutil.move(src, dst)
    prune_empty_dirs(src.parent, old_root)


def _delete_file(root: Path, indexed: IndexedFile) -> bool:
    path = to_path(root, indexed.relative_path)
    if not path.is_file():
        return False
    identity = read_identity(path)
    if identity is None or identity.key != indexed.key:
        _LOGGER.warning(
            "Refusing to delete %s: not a Tilawa file for %s", path, indexed.key
        )
        return False
    path.unlink()
    prune_empty_dirs(path.parent, root)
    return True


def _scan_tagged_files(root: Path) -> list[tuple[str, TrackIdentity, int]]:
    found: list[tuple[str, TrackIdentity, int]] = []
    if not root.is_dir():
        return found
    for path in root.rglob("*.mp3"):
        identity = read_identity(path)
        if identity is None:
            continue
        relative = path.relative_to(root).as_posix()
        found.append((relative, identity, path.stat().st_size))
    return found
