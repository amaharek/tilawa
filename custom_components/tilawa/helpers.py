"""Helpers shared by the Home Assistant layer of Tilawa."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_LIBRARY_PATH,
    CONF_MOSHAF_ID,
    CONF_RECITER_ID,
    CONF_SURAHS,
    DEFAULT_SUBFOLDER,
    DOMAIN,
    OPT_NAMES_LANGUAGE,
    OPT_TITLE_FORMAT,
    SUBENTRY_TYPE_SELECTION,
)
from .lib.models import (
    Catalogue,
    Language,
    Moshaf,
    NamingOptions,
    Selection,
    TitleFormat,
)
from .lib.naming import album_name
from .lib.surahs import format_range, parse_range


def selection_from_subentry(subentry: ConfigSubentry) -> Selection:
    """Build a Selection from a selection subentry."""
    surahs = subentry.data.get(CONF_SURAHS)
    return Selection(
        reciter_id=int(subentry.data[CONF_RECITER_ID]),
        moshaf_id=int(subentry.data[CONF_MOSHAF_ID]),
        surahs=parse_range(surahs) if surahs else None,
    )


def selection_to_data(selection: Selection) -> dict[str, Any]:
    """Serialise a Selection into subentry data."""
    return {
        CONF_RECITER_ID: selection.reciter_id,
        CONF_MOSHAF_ID: selection.moshaf_id,
        CONF_SURAHS: format_range(selection.surahs) if selection.surahs else None,
    }


def selections_of(entry: ConfigEntry) -> list[Selection]:
    """Return every selection configured on the entry."""
    return [
        selection_from_subentry(subentry)
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_SELECTION
    ]


def find_subentry(entry: ConfigEntry, selection_key: str) -> ConfigSubentry | None:
    """Return the selection subentry with the given key, if any."""
    for subentry in entry.subentries.values():
        if (
            subentry.subentry_type == SUBENTRY_TYPE_SELECTION
            and subentry.unique_id == selection_key
        ):
            return subentry
    return None


def naming_options_of(entry: ConfigEntry) -> NamingOptions:
    """Return the naming options stored in the entry options."""
    return NamingOptions(
        names_language=cast("Language", entry.options.get(OPT_NAMES_LANGUAGE, "ar")),
        title_format=cast(
            "TitleFormat", entry.options.get(OPT_TITLE_FORMAT, "number_ar")
        ),
    )


def library_root_of(entry: ConfigEntry) -> Path:
    """Return the configured library folder."""
    return Path(entry.data[CONF_LIBRARY_PATH])


def selection_title(
    catalogue: Catalogue, selection: Selection, language: Language
) -> str:
    """Return a human-readable title such as ``Al-Hussary — Hafs – Murattal (78-114)``."""
    reciter = catalogue.reciters.get(selection.reciter_id)
    moshaf = catalogue.moshafs.get(selection.moshaf_id)
    reciter_name = reciter.name(language) if reciter else f"#{selection.reciter_id}"
    album = (
        album_name(moshaf, catalogue, language) if moshaf else f"#{selection.moshaf_id}"
    )
    title = f"{reciter_name} — {album}"
    if selection.surahs is not None:
        title += f" ({format_range(selection.surahs)})"
    return title


def validate_surahs(
    text: str | None, moshaf: Moshaf
) -> tuple[frozenset[int] | None, str | None]:
    """Parse an optional surah range against a moshaf; return (surahs, error_key)."""
    if not text or not text.strip():
        return None, None
    try:
        surahs = parse_range(text)
    except ValueError:
        return None, "invalid_surahs"
    if not surahs & moshaf.surahs:
        return None, "surahs_not_available"
    return surahs, None


def default_library_path(hass: HomeAssistant) -> str:
    """Return ``<first media dir>/Quran``."""
    media_dirs = hass.config.media_dirs
    first = next(iter(media_dirs.values()), None) or hass.config.path("media")
    return str(Path(first) / DEFAULT_SUBFOLDER)


def get_loaded_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the single Tilawa entry if it is loaded."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    return None
