"""Tests for the config, subentry and options flows."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tilawa.const import (
    CONF_ALL_SURAHS,
    CONF_LIBRARY_PATH,
    CONF_MOSHAF_ID,
    CONF_RECITER_ID,
    CONF_SURAHS,
    DOMAIN,
    OPT_AUTO_SYNC,
    OPT_BANDWIDTH_LIMIT,
    OPT_MAX_PARALLEL,
    OPT_NAMES_LANGUAGE,
    OPT_NUMBER_SEPARATOR,
    OPT_REDOWNLOAD_CHANGED,
    OPT_TITLE_FORMAT,
    SUBENTRY_TYPE_SELECTION,
)
from custom_components.tilawa.lib.api import Mp3QuranConnectionError


@pytest.fixture
def mock_setup_entry() -> AsyncMock:
    with patch(
        "custom_components.tilawa.async_setup_entry", return_value=True
    ) as mocked:
        yield mocked


async def test_full_flow_creates_entry_with_first_selection(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_setup_entry: AsyncMock,
    library_path: str,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "free_space" in result["description_placeholders"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LIBRARY_PATH: library_path}
    )
    assert result["step_id"] == "naming"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            OPT_NAMES_LANGUAGE: "ar",
            OPT_TITLE_FORMAT: "number_ar",
            OPT_NUMBER_SEPARATOR: "space",
        },
    )
    assert result["step_id"] == "reciter"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECITER_ID: "118"}
    )
    assert result["step_id"] == "version"
    assert result["description_placeholders"] == {"reciter": "محمود خليل الحصري"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MOSHAF_ID: "118", CONF_ALL_SURAHS: False, CONF_SURAHS: "78-114"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.title == "Tilawa"
    assert entry.unique_id == DOMAIN
    assert entry.data == {CONF_LIBRARY_PATH: library_path}
    assert entry.options[OPT_NAMES_LANGUAGE] == "ar"
    assert entry.options[OPT_MAX_PARALLEL] == 2
    subentry = next(iter(entry.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_TYPE_SELECTION
    assert subentry.unique_id == "118:118"
    assert subentry.data == {
        CONF_RECITER_ID: 118,
        CONF_MOSHAF_ID: 118,
        CONF_SURAHS: "78-114",
    }
    assert subentry.title == "محمود خليل الحصري — حفص – مرتل (78-114)"
    assert mock_setup_entry.await_count == 1


async def test_flow_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_setup_entry: AsyncMock,
    library_path: str,
    tmp_path,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LIBRARY_PATH: "relative/path"}
    )
    assert result["errors"] == {"base": "path_not_allowed"}

    blocker = tmp_path / "file"
    blocker.write_text("x")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LIBRARY_PATH: str(blocker / "Quran")}
    )
    assert result["errors"] == {"base": "not_writable"}

    mock_client.async_fetch_catalogue.side_effect = Mp3QuranConnectionError("down")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LIBRARY_PATH: library_path}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.async_fetch_catalogue.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LIBRARY_PATH: library_path}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            OPT_NAMES_LANGUAGE: "eng",
            OPT_TITLE_FORMAT: "number_en",
            OPT_NUMBER_SEPARATOR: "hyphen",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RECITER_ID: "118"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MOSHAF_ID: "118", CONF_ALL_SURAHS: False, CONF_SURAHS: "200"},
    )
    assert result["errors"] == {CONF_SURAHS: "invalid_surahs"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MOSHAF_ID: "118", CONF_ALL_SURAHS: False, CONF_SURAHS: ""},
    )
    assert result["errors"] == {CONF_SURAHS: "surahs_required"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MOSHAF_ID: "118", CONF_ALL_SURAHS: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(result["result"].subentries.values()))
    assert subentry.data[CONF_SURAHS] is None
    assert subentry.title == "Mahmoud Khalil Al-Hussary — Hafs – Murattal"


async def test_single_instance(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] in ("already_configured", "single_instance_allowed")


async def test_subentry_flow_adds_and_rejects_duplicates(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with patch(
        "custom_components.tilawa.coordinator.TilawaSyncManager.async_request_sync"
    ) as request_sync:
        result = await hass.config_entries.subentries.async_init(
            (setup_entry.entry_id, SUBENTRY_TYPE_SELECTION),
            context={"source": SOURCE_USER},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {CONF_RECITER_ID: "118"}
        )
        assert result["step_id"] == "version"
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {CONF_MOSHAF_ID: "119"}
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["unique_id"] == "118:119"
        assert len(setup_entry.subentries) == 2
        assert request_sync.await_count == 1

    result = await hass.config_entries.subentries.async_init(
        (setup_entry.entry_id, SUBENTRY_TYPE_SELECTION), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_RECITER_ID: "118"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_MOSHAF_ID: "119"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_subentry_reconfigure_changes_range(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    subentry = next(iter(setup_entry.subentries.values()))
    with patch(
        "custom_components.tilawa.coordinator.TilawaSyncManager.async_request_sync"
    ) as request_sync:
        result = await hass.config_entries.subentries.async_init(
            (setup_entry.entry_id, SUBENTRY_TYPE_SELECTION),
            context={
                "source": "reconfigure",
                "subentry_id": subentry.subentry_id,
            },
        )
        assert result["step_id"] == "reconfigure"
        assert result["description_placeholders"]["available"] == "1-114"
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {CONF_ALL_SURAHS: False, CONF_SURAHS: "1, 36"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    updated = setup_entry.subentries[subentry.subentry_id]
    assert updated.data[CONF_SURAHS] == "1, 36"
    assert updated.title.endswith("(1, 36)")
    assert request_sync.await_count == 1


async def test_options_flow(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    with patch(
        "custom_components.tilawa.coordinator.TilawaSyncManager.async_request_retag"
    ) as request_retag:
        result = await hass.config_entries.options.async_init(setup_entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                OPT_NAMES_LANGUAGE: "eng",
                OPT_TITLE_FORMAT: "number_both",
                OPT_NUMBER_SEPARATOR: "spaced_hyphen",
                OPT_MAX_PARALLEL: 3,
                OPT_BANDWIDTH_LIMIT: 500,
                OPT_AUTO_SYNC: "daily",
                OPT_REDOWNLOAD_CHANGED: True,
            },
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options[OPT_NAMES_LANGUAGE] == "eng"
    assert setup_entry.options[OPT_MAX_PARALLEL] == 3
    assert setup_entry.options[OPT_AUTO_SYNC] == "daily"
    assert request_retag.await_count == 1
