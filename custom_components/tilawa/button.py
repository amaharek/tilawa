"""Buttons to start and cancel a sync."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TilawaConfigEntry, TilawaSyncManager
from .entity import TilawaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TilawaButtonDescription(ButtonEntityDescription):
    """Describes a Tilawa button."""

    press_fn: Callable[[TilawaSyncManager], Awaitable[None]]


BUTTONS: tuple[TilawaButtonDescription, ...] = (
    TilawaButtonDescription(
        key="sync_now", press_fn=lambda manager: manager.async_request_sync()
    ),
    TilawaButtonDescription(
        key="cancel_sync", press_fn=lambda manager: manager.async_cancel()
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TilawaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    async_add_entities(TilawaButton(entry, description) for description in BUTTONS)


class TilawaButton(TilawaEntity, ButtonEntity):
    """A button acting on the sync manager."""

    entity_description: TilawaButtonDescription

    def __init__(
        self, entry: TilawaConfigEntry, description: TilawaButtonDescription
    ) -> None:
        """Initialise the button."""
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Run the action."""
        await self.entity_description.press_fn(self.manager)
