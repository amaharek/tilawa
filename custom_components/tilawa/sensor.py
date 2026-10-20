"""Sensors describing the sync job and the library."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import TilawaConfigEntry, TilawaSyncManager
from .entity import TilawaEntity
from .lib.models import SyncState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TilawaSensorDescription(SensorEntityDescription):
    """Describes a Tilawa sensor."""

    value_fn: Callable[[TilawaSyncManager], StateType | datetime]
    attributes_fn: Callable[[TilawaSyncManager], dict[str, Any]] | None = None


SENSORS: tuple[TilawaSensorDescription, ...] = (
    TilawaSensorDescription(
        key="sync_status",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in SyncState],
        value_fn=lambda manager: manager.progress.state.value,
        attributes_fn=lambda manager: {
            "job": manager.progress.kind.value if manager.progress.kind else None,
            "current": manager.progress.current_key,
            "done": manager.progress.done,
            "total": manager.progress.total,
            "failed": manager.progress.failed,
            "error": manager.progress.error,
        },
    ),
    TilawaSensorDescription(
        key="sync_progress",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda manager: round(manager.progress.percent, 1),
    ),
    TilawaSensorDescription(
        key="files",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda manager: manager.stats.files,
    ),
    TilawaSensorDescription(
        key="library_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda manager: manager.stats.bytes,
    ),
    TilawaSensorDescription(
        key="last_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda manager: manager.last_success,
    ),
    TilawaSensorDescription(
        key="reciters",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda manager: manager.stats.reciters,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TilawaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(TilawaSensor(entry, description) for description in SENSORS)


class TilawaSensor(TilawaEntity, SensorEntity):
    """A sensor fed by the sync manager."""

    entity_description: TilawaSensorDescription

    def __init__(
        self, entry: TilawaConfigEntry, description: TilawaSensorDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value."""
        return self.entity_description.value_fn(self.manager)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return job details for the status sensor."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.manager)
