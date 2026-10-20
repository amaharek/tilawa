"""Repair fix flows: orphaned files and selections removed upstream."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol

from .const import (
    CONF_DELETE_FILES,
    DOMAIN,
    ISSUE_ORPHANED_FILES,
    ISSUE_SELECTION_MISSING,
)
from .coordinator import TilawaConfigEntry
from .helpers import find_subentry, get_loaded_entry


class _SelectionRepairFlow(RepairsFlow):
    """Base for flows that act on one selection key."""

    @property
    def _selection_key(self) -> str:
        key = (self.data or {}).get("selection_key")
        return str(key) if key is not None else ""

    def _placeholders(self) -> dict[str, str] | None:
        issue = ir.async_get(self.hass).async_get_issue(self.handler, self.issue_id)
        return issue.translation_placeholders if issue else None

    def _entry(self) -> TilawaConfigEntry | None:
        entry: TilawaConfigEntry | None = get_loaded_entry(self.hass)
        return entry


class OrphanedFilesRepairFlow(_SelectionRepairFlow):
    """Ask whether to delete files of a removed selection; default keeps them."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Start with the confirm step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Delete or keep."""
        if user_input is not None:
            entry = self._entry()
            if user_input.get(CONF_DELETE_FILES) and entry is not None:
                await entry.runtime_data.sync.async_delete_selection_files(
                    self._selection_key
                )
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_DELETE_FILES, default=False): bool}
            ),
            description_placeholders=self._placeholders(),
        )


class MissingSelectionRepairFlow(_SelectionRepairFlow):
    """Remove a selection the catalogue no longer offers (files are kept)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Start with the confirm step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Remove the subentry on confirmation."""
        if user_input is not None:
            entry = self._entry()
            if entry is not None and (
                subentry := find_subentry(entry, self._selection_key)
            ):
                self.hass.config_entries.async_remove_subentry(
                    entry, subentry.subentry_id
                )
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=self._placeholders(),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix flow for an issue."""
    if issue_id.startswith(f"{ISSUE_ORPHANED_FILES}_"):
        return OrphanedFilesRepairFlow()
    if issue_id.startswith(f"{ISSUE_SELECTION_MISSING}_"):
        return MissingSelectionRepairFlow()
    return ConfirmRepairFlow()


__all__ = ["DOMAIN", "async_create_fix_flow"]
