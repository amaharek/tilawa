"""Base entity for Tilawa."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME
from .coordinator import TilawaConfigEntry, TilawaSyncManager


class TilawaEntity(Entity):
    """An entity of the single Tilawa device, updated by the sync manager."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: TilawaConfigEntry, key: str) -> None:
        """Bind the entity to the entry and its sync manager."""
        self.entry = entry
        self.manager: TilawaSyncManager = entry.runtime_data.sync
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=NAME,
            model="Quran recitation library",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=entry.runtime_data.version,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to manager updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
