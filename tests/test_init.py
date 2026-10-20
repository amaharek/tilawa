"""Tests for setup, unload and the catalogue coordinator."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tilawa.const import DOMAIN
from custom_components.tilawa.lib.api import Mp3QuranConnectionError


async def test_setup_and_unload(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED
    assert (
        setup_entry.runtime_data.catalogue.data.reciters[118].name_en
        == "Mahmoud Khalil Al-Hussary"
    )
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, setup_entry.entry_id)}
    )
    assert device is not None
    assert device.name == "Tilawa"
    assert hass.states.get("sensor.tilawa_sync_status").state == "idle"
    assert hass.states.get("binary_sensor.tilawa_mp3quran_net_reachable").state == "on"
    for service in ("sync", "add_selection", "remove_selection", "retag"):
        assert hass.services.has_service(DOMAIN, service)

    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_api_down_and_no_cache(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.async_fetch_catalogue.side_effect = Mp3QuranConnectionError("down")
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_remove_entry_clears_storage(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_remove(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(DOMAIN)
