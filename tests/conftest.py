"""Shared fixtures for Tilawa tests."""

from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from mutagen.id3 import APIC, ID3, TPE1, TPE2, Encoding
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tilawa.const import (
    CONF_LIBRARY_PATH,
    CONF_MOSHAF_ID,
    CONF_RECITER_ID,
    CONF_SURAHS,
    DEFAULT_OPTIONS,
    DOMAIN,
    SUBENTRY_TYPE_SELECTION,
)
from custom_components.tilawa.lib.api import build_catalogue
from custom_components.tilawa.lib.models import LANGUAGES, Catalogue, RemoteFile

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
# One MPEG-1 Layer III frame: 128 kbps, 44.1 kHz, stereo, no padding -> 417 bytes.
MP3_FRAME = bytes.fromhex("FFFB9000") + bytes(413)


def load_fixture(name: str) -> dict[str, Any]:
    """Load a captured API response from tests/fixtures."""
    data: dict[str, Any] = json.loads(
        (FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8")
    )
    return data


async def run_inline[T](func: Callable[..., T], /, *args: Any) -> T:
    """RunBlocking implementation that runs synchronously (no threads in tests)."""
    return func(*args)


@pytest.fixture
def payloads() -> dict[tuple[str, str], dict[str, Any]]:
    """Raw API payloads for both languages, as the client would fetch them."""
    return {
        (path, lang): load_fixture(f"{path}_{lang}")
        for path in ("reciters", "suwar", "riwayat", "moshaf")
        for lang in LANGUAGES
    }


@pytest.fixture
def catalogue(payloads: dict[tuple[str, str], dict[str, Any]]) -> Catalogue:
    """A catalogue built from the captured fixtures."""
    return build_catalogue(payloads, fetched_at=FETCHED_AT)  # type: ignore[arg-type]


@pytest.fixture
def make_mp3() -> Callable[..., bytes]:
    """Factory writing a tiny but structurally valid MP3, optionally with old tags."""

    def _make(path: Path, *, frames: int = 20, legacy_tags: bool = False) -> bytes:
        audio = MP3_FRAME * frames
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        if legacy_tags:
            id3 = ID3()
            id3.add(TPE1(encoding=Encoding.UTF8, text=["Someone"]))
            id3.add(TPE2(encoding=Encoding.UTF8, text=["www.mp3quran.net"]))
            id3.add(
                APIC(
                    encoding=Encoding.LATIN1,
                    mime="image/png",
                    type=3,
                    desc="",
                    data=b"\x89PNG\r\n\x1a\n",
                )
            )
            id3.save(path, v2_version=3)
        return audio

    return _make


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/tilawa in every test."""


@pytest.fixture
def mock_client(catalogue: Catalogue) -> Generator[MagicMock]:
    """Replace the API client everywhere it is constructed."""
    client = MagicMock()
    client.async_ping = AsyncMock()
    client.async_fetch_catalogue = AsyncMock(return_value=catalogue)
    client.async_head = AsyncMock(return_value=RemoteFile(10, '"e"'))
    with (
        patch("custom_components.tilawa.Mp3QuranClient", return_value=client),
        patch(
            "custom_components.tilawa.config_flow.Mp3QuranClient", return_value=client
        ),
    ):
        yield client


@pytest.fixture
def library_path(hass: HomeAssistant, tmp_path: Path) -> str:
    """A writable, allowed library folder for the test instance."""
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    return str(tmp_path / "Quran")


@pytest.fixture
def mock_config_entry(library_path: str) -> MockConfigEntry:
    """A config entry with one selection (Al-Hussary, Hafs Murattal, Juz' Amma)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Tilawa",
        unique_id=DOMAIN,
        data={CONF_LIBRARY_PATH: library_path},
        options=dict(DEFAULT_OPTIONS),
        subentries_data=[
            ConfigSubentryData(
                data={CONF_RECITER_ID: 118, CONF_MOSHAF_ID: 118, CONF_SURAHS: "78-114"},
                subentry_type=SUBENTRY_TYPE_SELECTION,
                title="Al-Hussary — Hafs – Murattal (78-114)",
                unique_id="118:118",
            )
        ],
    )


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_client: MagicMock
) -> MockConfigEntry:
    """Set the entry up and wait for it."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
