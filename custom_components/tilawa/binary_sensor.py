"""Binary sensor reporting whether mp3quran.net is reachable."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TilawaConfigEntry
from .entity import TilawaEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TilawaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connectivity sensor."""
    async_add_entities([TilawaApiBinarySensor(entry)])


class TilawaApiBinarySensor(TilawaEntity, BinarySensorEntity):
    """On while the catalogue API answers."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: TilawaConfigEntry) -> None:
        """Initialise."""
        super().__init__(entry, "api")
        self._coordinator = entry.runtime_data.catalogue

    async def async_added_to_hass(self) -> None:
        """Also follow catalogue refreshes."""
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))

    @property
    def is_on(self) -> bool:
        """Return True when the API was reachable at the last check."""
        return self._coordinator.api_available
