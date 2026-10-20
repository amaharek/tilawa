"""Config, subentry, options and reconfigure flows for Tilawa."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import shutil
from typing import Any

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
import voluptuous as vol

from .const import (
    AUTO_SYNC_OPTIONS,
    BANDWIDTH_LIMIT_MAX,
    CONF_ALL_SURAHS,
    CONF_LIBRARY_PATH,
    CONF_MOSHAF_ID,
    CONF_MOVE_FILES,
    CONF_PENDING_MOVE_FROM,
    CONF_RECITER_ID,
    CONF_SURAHS,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_PARALLEL_LIMIT,
    NAME,
    OPT_AUTO_SYNC,
    OPT_BANDWIDTH_LIMIT,
    OPT_MAX_PARALLEL,
    OPT_NAMES_LANGUAGE,
    OPT_NUMBER_SEPARATOR,
    OPT_REDOWNLOAD_CHANGED,
    OPT_TITLE_FORMAT,
    SUBENTRY_TYPE_SELECTION,
)
from .coordinator import TilawaConfigEntry
from .helpers import (
    default_library_path,
    naming_options_of,
    selection_from_subentry,
    selection_title,
    selection_to_data,
    validate_surahs,
)
from .lib.api import Mp3QuranClient, Mp3QuranError
from .lib.models import (
    LANGUAGES,
    NUMBER_SEPARATORS,
    TITLE_FORMATS,
    Catalogue,
    Language,
    Moshaf,
    Reciter,
    Selection,
)
from .lib.naming import album_name
from .lib.surahs import format_range
from .lib.sync import LibraryNotWritable, check_writable

STEP_NAMING_SCHEMA = vol.Schema(
    {
        vol.Required(OPT_NAMES_LANGUAGE): SelectSelector(
            SelectSelectorConfig(
                options=list(LANGUAGES),
                translation_key=OPT_NAMES_LANGUAGE,
                mode=SelectSelectorMode.LIST,
            )
        ),
        vol.Required(OPT_TITLE_FORMAT): SelectSelector(
            SelectSelectorConfig(
                options=list(TITLE_FORMATS),
                translation_key=OPT_TITLE_FORMAT,
                mode=SelectSelectorMode.LIST,
            )
        ),
        vol.Required(OPT_NUMBER_SEPARATOR): SelectSelector(
            SelectSelectorConfig(
                options=list(NUMBER_SEPARATORS),
                translation_key=OPT_NUMBER_SEPARATOR,
                mode=SelectSelectorMode.LIST,
            )
        ),
    }
)

OPTIONS_SCHEMA = STEP_NAMING_SCHEMA.extend(
    {
        vol.Required(OPT_MAX_PARALLEL): vol.All(
            NumberSelector(
                NumberSelectorConfig(
                    min=1, max=MAX_PARALLEL_LIMIT, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Coerce(int),
        ),
        vol.Required(OPT_BANDWIDTH_LIMIT): vol.All(
            NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=BANDWIDTH_LIMIT_MAX,
                    step=1,
                    unit_of_measurement="kB/s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Coerce(int),
        ),
        vol.Required(OPT_AUTO_SYNC): SelectSelector(
            SelectSelectorConfig(
                options=list(AUTO_SYNC_OPTIONS),
                translation_key=OPT_AUTO_SYNC,
                mode=SelectSelectorMode.LIST,
            )
        ),
        vol.Required(OPT_REDOWNLOAD_CHANGED): BooleanSelector(),
    }
)


def _validate_path_blocking(path: str) -> str | None:
    """Return an error key if ``path`` cannot be used as the library folder."""
    if not Path(path).is_absolute():
        return "invalid_path"
    try:
        check_writable(Path(path))
    except LibraryNotWritable:
        return "not_writable"
    return None


def _free_space_blocking(path: str) -> str:
    """Return free space of the volume holding ``path`` (or its nearest parent)."""
    candidate = Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        free = shutil.disk_usage(candidate).free
    except OSError:
        return "?"
    return f"{free / 1_000_000_000:.1f} GB"


async def _async_validate_path(hass: HomeAssistant, path: str) -> str | None:
    if not hass.config.is_allowed_path(path):
        return "path_not_allowed"
    return await hass.async_add_executor_job(_validate_path_blocking, path)


def _reciter_selector(catalogue: Catalogue, language: Language) -> SelectSelector:
    options = [
        SelectOptionDict(
            value=str(reciter.id),
            label=f"{reciter.name(language)} ({len(reciter.moshafs)})",
        )
        for reciter in catalogue.reciters.values()
    ]
    return SelectSelector(
        SelectSelectorConfig(
            options=options, mode=SelectSelectorMode.DROPDOWN, sort=True
        )
    )


def _version_schema(
    catalogue: Catalogue, reciter: Reciter, language: Language
) -> vol.Schema:
    options = [
        SelectOptionDict(
            value=str(moshaf.id),
            label=f"{album_name(moshaf, catalogue, language)} ({len(moshaf.surahs)})",
        )
        for moshaf in reciter.moshafs
    ]
    return vol.Schema(
        {
            vol.Required(CONF_MOSHAF_ID): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
            ),
            vol.Required(CONF_ALL_SURAHS, default=True): BooleanSelector(),
            vol.Optional(CONF_SURAHS): TextSelector(),
        }
    )


def _parse_surah_input(
    user_input: Mapping[str, Any], moshaf: Moshaf
) -> tuple[frozenset[int] | None, str | None]:
    """Return the chosen surahs: ``None`` for everything, else the validated range."""
    if user_input.get(CONF_ALL_SURAHS, True):
        return None, None
    text = (user_input.get(CONF_SURAHS) or "").strip()
    if not text:
        return None, "surahs_required"
    return validate_surahs(text, moshaf)


def _build_selection(
    catalogue: Catalogue, reciter_id: int, user_input: Mapping[str, Any]
) -> tuple[Selection | None, dict[str, str]]:
    moshaf = catalogue.moshafs.get(int(user_input[CONF_MOSHAF_ID]))
    if moshaf is None or moshaf.reciter_id != reciter_id:
        return None, {"base": "unknown_moshaf"}
    surahs, error = _parse_surah_input(user_input, moshaf)
    if error:
        return None, {CONF_SURAHS: error}
    return Selection(reciter_id, moshaf.id, surahs), {}


class TilawaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Tilawa: folder, naming, then the first reciter."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = dict(DEFAULT_OPTIONS)
        self._catalogue: Catalogue | None = None
        self._reciter_id: int | None = None

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: Any
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry flows this integration offers."""
        return {SUBENTRY_TYPE_SELECTION: SelectionSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> TilawaOptionsFlow:
        """Return the options flow."""
        return TilawaOptionsFlow()

    @property
    def _language(self) -> Language:
        return self._options.get(OPT_NAMES_LANGUAGE, "ar")  # type: ignore[no-any-return]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: choose the library folder (and check the API)."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        path = default_library_path(self.hass)
        if user_input is not None:
            path = user_input[CONF_LIBRARY_PATH].strip()
            if error := await _async_validate_path(self.hass, path):
                errors["base"] = error
            else:
                try:
                    client = Mp3QuranClient(async_get_clientsession(self.hass))
                    self._catalogue = await client.async_fetch_catalogue()
                except Mp3QuranError:
                    errors["base"] = "cannot_connect"
            if not errors:
                self._data[CONF_LIBRARY_PATH] = path
                return await self.async_step_naming()
        free_space = await self.hass.async_add_executor_job(_free_space_blocking, path)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_LIBRARY_PATH): TextSelector()}),
                {CONF_LIBRARY_PATH: path},
            ),
            errors=errors,
            description_placeholders={"free_space": free_space},
        )

    async def async_step_naming(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: language of names and title format."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_reciter()
        return self.async_show_form(
            step_id="naming",
            data_schema=self.add_suggested_values_to_schema(
                STEP_NAMING_SCHEMA, self._options
            ),
        )

    async def async_step_reciter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: pick the first reciter."""
        assert self._catalogue is not None
        if user_input is not None:
            self._reciter_id = int(user_input[CONF_RECITER_ID])
            return await self.async_step_version()
        return self.async_show_form(
            step_id="reciter",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RECITER_ID): _reciter_selector(
                        self._catalogue, self._language
                    )
                }
            ),
        )

    async def async_step_version(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: pick the version and an optional surah range, then create."""
        assert self._catalogue is not None and self._reciter_id is not None
        reciter = self._catalogue.reciters[self._reciter_id]
        errors: dict[str, str] = {}
        if user_input is not None:
            selection, errors = _build_selection(
                self._catalogue, reciter.id, user_input
            )
            if selection is not None:
                title = selection_title(self._catalogue, selection, self._language)
                return self.async_create_entry(
                    title=NAME,
                    data=self._data,
                    options=self._options,
                    subentries=[
                        ConfigSubentryData(
                            data=selection_to_data(selection),
                            subentry_type=SUBENTRY_TYPE_SELECTION,
                            title=title,
                            unique_id=selection.key,
                        )
                    ],
                )
        return self.async_show_form(
            step_id="version",
            data_schema=_version_schema(self._catalogue, reciter, self._language),
            errors=errors,
            description_placeholders={"reciter": reciter.name(self._language)},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the library folder, optionally moving the files."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            path = user_input[CONF_LIBRARY_PATH].strip()
            current = entry.data[CONF_LIBRARY_PATH]
            if path == current:
                return self.async_abort(reason="reconfigure_successful")
            if error := await _async_validate_path(self.hass, path):
                errors["base"] = error
            else:
                data = {
                    k: v for k, v in entry.data.items() if k != CONF_PENDING_MOVE_FROM
                }
                data[CONF_LIBRARY_PATH] = path
                if user_input[CONF_MOVE_FILES]:
                    data[CONF_PENDING_MOVE_FROM] = current
                return self.async_update_reload_and_abort(entry, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_LIBRARY_PATH): TextSelector(),
                vol.Required(CONF_MOVE_FILES, default=True): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_LIBRARY_PATH: entry.data[CONF_LIBRARY_PATH]}
            ),
            errors=errors,
        )


class SelectionSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one reciter/version selection."""

    def __init__(self) -> None:
        """Initialise flow state."""
        self._reciter_id: int | None = None

    def _loaded_entry(self) -> TilawaConfigEntry | None:
        entry: TilawaConfigEntry = self._get_entry()
        return entry if entry.state is ConfigEntryState.LOADED else None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the reciter."""
        entry = self._loaded_entry()
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        catalogue = entry.runtime_data.catalogue.data
        language = naming_options_of(entry).names_language
        if user_input is not None:
            self._reciter_id = int(user_input[CONF_RECITER_ID])
            return await self.async_step_version()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_RECITER_ID): _reciter_selector(catalogue, language)}
            ),
        )

    async def async_step_version(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the version and optional range, then create the selection."""
        entry = self._loaded_entry()
        if entry is None or self._reciter_id is None:
            return self.async_abort(reason="entry_not_loaded")
        catalogue = entry.runtime_data.catalogue.data
        language = naming_options_of(entry).names_language
        reciter = catalogue.reciters[self._reciter_id]
        errors: dict[str, str] = {}
        if user_input is not None:
            selection, errors = _build_selection(catalogue, reciter.id, user_input)
            if selection is not None:
                return self.async_create_entry(
                    title=selection_title(catalogue, selection, language),
                    data=selection_to_data(selection),
                    unique_id=selection.key,
                )
        return self.async_show_form(
            step_id="version",
            data_schema=_version_schema(catalogue, reciter, language),
            errors=errors,
            description_placeholders={"reciter": reciter.name(language)},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the surah range of an existing selection."""
        entry = self._loaded_entry()
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        subentry = self._get_reconfigure_subentry()
        catalogue = entry.runtime_data.catalogue.data
        language = naming_options_of(entry).names_language
        selection = selection_from_subentry(subentry)
        moshaf = catalogue.moshafs.get(selection.moshaf_id)
        if moshaf is None:
            return self.async_abort(reason="selection_missing_upstream")
        errors: dict[str, str] = {}
        if user_input is not None:
            surahs, error = _parse_surah_input(user_input, moshaf)
            if error:
                errors[CONF_SURAHS] = error
            else:
                updated = Selection(selection.reciter_id, selection.moshaf_id, surahs)
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    data=selection_to_data(updated),
                    title=selection_title(catalogue, updated, language),
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_ALL_SURAHS, default=True): BooleanSelector(),
                        vol.Optional(CONF_SURAHS): TextSelector(),
                    }
                ),
                {
                    CONF_ALL_SURAHS: selection.surahs is None,
                    CONF_SURAHS: format_range(selection.surahs)
                    if selection.surahs
                    else "",
                },
            ),
            errors=errors,
            description_placeholders={
                "selection": selection_title(catalogue, selection, language),
                "available": format_range(moshaf.surahs),
            },
        )


class TilawaOptionsFlow(OptionsFlow):
    """Naming and sync options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, {**DEFAULT_OPTIONS, **self.config_entry.options}
            ),
        )


__all__ = [
    "SOURCE_USER",
    "SelectionSubentryFlow",
    "TilawaConfigFlow",
    "TilawaOptionsFlow",
]
