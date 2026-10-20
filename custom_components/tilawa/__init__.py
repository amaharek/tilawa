"""Tilawa: a tagged Quran recitation library for Music Assistant, fed by mp3quran.net."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_loaded_integration

from .const import DOMAIN, REPO_URL
from .coordinator import (
    TilawaCatalogueCoordinator,
    TilawaConfigEntry,
    TilawaRuntimeData,
    TilawaSyncManager,
)
from .lib.api import Mp3QuranClient
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TilawaConfigEntry) -> bool:
    """Set up Tilawa from a config entry."""
    version = async_get_loaded_integration(hass, DOMAIN).version or "0"
    client = Mp3QuranClient(
        async_get_clientsession(hass), user_agent=f"Tilawa/{version} (+{REPO_URL})"
    )
    catalogue = TilawaCatalogueCoordinator(hass, entry, client)
    await catalogue.async_config_entry_first_refresh()

    manager = TilawaSyncManager(hass, entry, client, catalogue)
    entry.runtime_data = TilawaRuntimeData(
        client=client, catalogue=catalogue, sync=manager, version=str(version)
    )
    await manager.async_load()
    catalogue.check_selections(catalogue.data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    manager.async_start()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: TilawaConfigEntry) -> None:
    """Options or subentries changed."""
    await entry.runtime_data.sync.async_handle_entry_update()


async def async_unload_entry(hass: HomeAssistant, entry: TilawaConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.sync.async_shutdown()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: TilawaConfigEntry) -> None:
    """Delete persisted state. Downloaded files are left in place."""
    client = Mp3QuranClient(async_get_clientsession(hass))
    catalogue = TilawaCatalogueCoordinator(hass, entry, client)
    manager = TilawaSyncManager(hass, entry, client, catalogue)
    await catalogue.async_remove_cache()
    await manager.async_remove_storage()
