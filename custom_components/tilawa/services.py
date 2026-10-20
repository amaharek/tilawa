"""Actions: sync, add_selection, remove_selection, retag."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    CONF_DELETE_FILES,
    CONF_MOSHAF_ID,
    CONF_RECITER_ID,
    CONF_SURAHS,
    DOMAIN,
    SERVICE_ADD_SELECTION,
    SERVICE_REMOVE_SELECTION,
    SERVICE_RETAG,
    SERVICE_SYNC,
    SUBENTRY_TYPE_SELECTION,
)
from .coordinator import TilawaConfigEntry
from .helpers import (
    find_subentry,
    get_loaded_entry,
    naming_options_of,
    selection_title,
    selection_to_data,
    validate_surahs,
)
from .lib.models import Selection, selection_key

SYNC_SCHEMA = vol.Schema(
    {
        vol.Inclusive(CONF_RECITER_ID, "selection"): cv.positive_int,
        vol.Inclusive(CONF_MOSHAF_ID, "selection"): cv.positive_int,
    }
)
ADD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RECITER_ID): cv.positive_int,
        vol.Required(CONF_MOSHAF_ID): cv.positive_int,
        vol.Optional(CONF_SURAHS): cv.string,
    }
)
REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RECITER_ID): cv.positive_int,
        vol.Required(CONF_MOSHAF_ID): cv.positive_int,
        vol.Optional(CONF_DELETE_FILES, default=False): cv.boolean,
    }
)


def _entry(hass: HomeAssistant) -> TilawaConfigEntry:
    entry: TilawaConfigEntry | None = get_loaded_entry(hass)
    if entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    return entry


async def _async_sync(call: ServiceCall) -> None:
    entry = _entry(call.hass)
    selection: Selection | None = None
    if CONF_RECITER_ID in call.data:
        key = selection_key(call.data[CONF_RECITER_ID], call.data[CONF_MOSHAF_ID])
        subentry = find_subentry(entry, key)
        if subentry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_selection",
                translation_placeholders={"selection": key},
            )
        selection = Selection(call.data[CONF_RECITER_ID], call.data[CONF_MOSHAF_ID])
    await entry.runtime_data.sync.async_request_sync(selection)


async def _async_add_selection(call: ServiceCall) -> None:
    entry = _entry(call.hass)
    catalogue = entry.runtime_data.catalogue.data
    reciter_id: int = call.data[CONF_RECITER_ID]
    moshaf_id: int = call.data[CONF_MOSHAF_ID]
    reciter = catalogue.reciters.get(reciter_id)
    if reciter is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_reciter",
            translation_placeholders={"reciter_id": str(reciter_id)},
        )
    moshaf = catalogue.moshafs.get(moshaf_id)
    if moshaf is None or moshaf.reciter_id != reciter_id:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_moshaf",
            translation_placeholders={
                "moshaf_id": str(moshaf_id),
                "reciter": reciter.name_en,
            },
        )
    surahs, error = validate_surahs(call.data.get(CONF_SURAHS), moshaf)
    if error:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=error,
            translation_placeholders={"surahs": str(call.data.get(CONF_SURAHS, ""))},
        )
    selection = Selection(reciter_id, moshaf_id, surahs)
    if find_subentry(entry, selection.key) is not None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="already_selected",
            translation_placeholders={"selection": selection.key},
        )
    language = naming_options_of(entry).names_language
    call.hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=selection_to_data(selection),  # type: ignore[arg-type]
            subentry_type=SUBENTRY_TYPE_SELECTION,
            title=selection_title(catalogue, selection, language),
            unique_id=selection.key,
        ),
    )


async def _async_remove_selection(call: ServiceCall) -> None:
    entry = _entry(call.hass)
    key = selection_key(call.data[CONF_RECITER_ID], call.data[CONF_MOSHAF_ID])
    subentry = find_subentry(entry, key)
    manager = entry.runtime_data.sync
    has_files = bool(manager.index.keys_for_selection(key))
    if subentry is None and not has_files:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_selection",
            translation_placeholders={"selection": key},
        )
    if call.data[CONF_DELETE_FILES] and has_files:
        await manager.async_delete_selection_files(key)
    if subentry is not None:
        call.hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)


async def _async_retag(call: ServiceCall) -> None:
    entry = _entry(call.hass)
    await entry.runtime_data.sync.async_request_retag()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions (called from ``async_setup``)."""
    hass.services.async_register(DOMAIN, SERVICE_SYNC, _async_sync, schema=SYNC_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_SELECTION, _async_add_selection, schema=ADD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_SELECTION, _async_remove_selection, schema=REMOVE_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_RETAG, _async_retag)
