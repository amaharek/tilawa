"""Diagnostics download for Tilawa."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import TilawaConfigEntry
from .helpers import selections_of

# Nothing stored is secret today; kept so new fields get a redaction decision.
TO_REDACT: set[str] = set()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TilawaConfigEntry
) -> dict[str, Any]:
    """Return configuration, selections, library and sync state."""
    runtime = entry.runtime_data
    manager = runtime.sync
    catalogue = runtime.catalogue.data
    per_selection = {
        selection.key: len(manager.index.keys_for_selection(selection.key))
        for selection in selections_of(entry)
    }
    data = {
        "version": runtime.version,
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
            "subentries": [
                subentry.as_dict() for subentry in entry.subentries.values()
            ],
        },
        "catalogue": {
            "fetched_at": catalogue.fetched_at.isoformat() if catalogue else None,
            "reciters": len(catalogue.reciters) if catalogue else 0,
            "moshafs": len(catalogue.moshafs) if catalogue else 0,
            "api_available": runtime.catalogue.api_available,
            "last_update_success": runtime.catalogue.last_update_success,
        },
        "library": {
            "files": manager.stats.files,
            "bytes": manager.stats.bytes,
            "files_per_selection": per_selection,
        },
        "sync": {
            "state": manager.state.value,
            "running": manager.is_running,
            "progress": {
                "done": manager.progress.done,
                "total": manager.progress.total,
                "failed": manager.progress.failed,
                "bytes_done": manager.progress.bytes_done,
                "bytes_total": manager.progress.bytes_total,
            },
            "last_success": manager.last_success.isoformat()
            if manager.last_success
            else None,
            "last_result": manager.last_result.to_dict()
            if manager.last_result
            else None,
            "errors": manager.errors,
        },
    }
    return async_redact_data(data, TO_REDACT)
