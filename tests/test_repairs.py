"""Tests for repair issues and their fix flows."""

from datetime import UTC, datetime
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tilawa.const import DOMAIN, ISSUE_ORPHANED_FILES
from custom_components.tilawa.lib.models import IndexedFile
from custom_components.tilawa.repairs import async_create_fix_flow


async def test_removing_a_selection_with_files_raises_a_fixable_issue(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    manager = setup_entry.runtime_data.sync
    manager.index.add(
        IndexedFile(
            key="118:118:78",
            relative_path="x/y/078.mp3",
            size=5,
            source_etag=None,
            naming_fingerprint="1:ar:number_ar",
            downloaded_at=datetime.now(UTC),
        )
    )
    subentry = next(iter(setup_entry.subentries.values()))
    hass.config_entries.async_remove_subentry(setup_entry, subentry.subentry_id)
    await hass.async_block_till_done()

    issue_id = f"{ISSUE_ORPHANED_FILES}_118:118"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_placeholders["count"] == "1"
    assert hass.states.get("sensor.tilawa_reciters").state == "0"

    flow = await async_create_fix_flow(hass, issue_id, issue.data)
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = issue_id
    flow.data = issue.data
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    with patch(
        "custom_components.tilawa.coordinator.TilawaSyncManager.async_delete_selection_files"
    ) as delete_files:
        result = await flow.async_step_confirm({"delete_files": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert delete_files.await_count == 1
    assert delete_files.await_args.args[0] == "118:118"


async def test_diagnostics(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    from custom_components.tilawa.diagnostics import async_get_config_entry_diagnostics  # noqa: PLC0415

    data = await async_get_config_entry_diagnostics(hass, setup_entry)
    assert data["catalogue"]["reciters"] == 5
    assert data["library"] == {
        "files": 0,
        "bytes": 0,
        "files_per_selection": {"118:118": 0},
    }
    assert data["sync"]["state"] == "idle"
    assert data["entry"]["subentries"][0]["unique_id"] == "118:118"
