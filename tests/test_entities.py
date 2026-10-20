"""Tests for sensors, binary sensor and buttons."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_sensors_reflect_manager_state(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    assert hass.states.get("sensor.tilawa_sync_status").state == "idle"
    assert hass.states.get("sensor.tilawa_sync_progress").state == "0.0"
    assert hass.states.get("sensor.tilawa_files").state == "0"
    assert float(hass.states.get("sensor.tilawa_library_size").state) == 0.0
    assert hass.states.get("sensor.tilawa_last_successful_sync").state == "unknown"
    assert hass.states.get("sensor.tilawa_reciters").state == "1"
    status = hass.states.get("sensor.tilawa_sync_status")
    assert status.attributes["done"] == 0
    assert status.attributes["options"] == [
        "idle",
        "syncing",
        "retagging",
        "moving",
        "error",
    ]


async def test_buttons_call_manager(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with (
        patch(
            "custom_components.tilawa.coordinator.TilawaSyncManager.async_request_sync"
        ) as request_sync,
        patch(
            "custom_components.tilawa.coordinator.TilawaSyncManager.async_cancel"
        ) as cancel,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.tilawa_sync_now"}, blocking=True
        )
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.tilawa_cancel_sync"}, blocking=True
        )
    assert request_sync.await_count == 1
    assert cancel.await_count == 1
