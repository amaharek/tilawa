"""Tests for the actions."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tilawa.const import (
    CONF_DELETE_FILES,
    CONF_MOSHAF_ID,
    CONF_RECITER_ID,
    CONF_SURAHS,
    DOMAIN,
)


async def test_add_and_remove_selection(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with patch(
        "custom_components.tilawa.coordinator.TilawaSyncManager.async_request_sync"
    ) as request_sync:
        await hass.services.async_call(
            DOMAIN,
            "add_selection",
            {CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 119, CONF_SURAHS: "1-3"},
            blocking=True,
        )
        await hass.async_block_till_done()
    assert len(setup_entry.subentries) == 2
    added = next(s for s in setup_entry.subentries.values() if s.unique_id == "118:119")
    assert added.data[CONF_SURAHS] == "1-3"
    assert request_sync.await_count == 1

    with pytest.raises(ServiceValidationError, match="already"):
        await hass.services.async_call(
            DOMAIN,
            "add_selection",
            {CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 119},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="No reciter"):
        await hass.services.async_call(
            DOMAIN,
            "add_selection",
            {CONF_RECITER_ID: 1, CONF_MOSHAF_ID: 1},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="does not belong"):
        await hass.services.async_call(
            DOMAIN,
            "add_selection",
            {CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 123},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="not a valid surah range"):
        await hass.services.async_call(
            DOMAIN,
            "add_selection",
            {CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 120, CONF_SURAHS: "x"},
            blocking=True,
        )

    await hass.services.async_call(
        DOMAIN,
        "remove_selection",
        {CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 119, CONF_DELETE_FILES: False},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(setup_entry.subentries) == 1
    with pytest.raises(ServiceValidationError, match="No selection"):
        await hass.services.async_call(
            DOMAIN,
            "remove_selection",
            {CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 119},
            blocking=True,
        )


async def test_sync_and_retag_actions(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with (
        patch(
            "custom_components.tilawa.coordinator.TilawaSyncManager.async_request_sync"
        ) as request_sync,
        patch(
            "custom_components.tilawa.coordinator.TilawaSyncManager.async_request_retag"
        ) as request_retag,
    ):
        await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
        await hass.services.async_call(
            DOMAIN, "sync", {CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 118}, blocking=True
        )
        await hass.services.async_call(DOMAIN, "retag", {}, blocking=True)
        with pytest.raises(ServiceValidationError, match="No selection"):
            await hass.services.async_call(
                DOMAIN, "sync", {CONF_RECITER_ID: 1, CONF_MOSHAF_ID: 1}, blocking=True
            )
    assert request_sync.await_count == 2
    assert request_sync.await_args_list[1].args[0].key == "118:118"
    assert request_retag.await_count == 1
