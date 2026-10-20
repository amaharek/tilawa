"""Tests for the API client and catalogue parsing."""

from dataclasses import replace
from typing import Any

import aiohttp
from aioresponses import aioresponses
import pytest

from custom_components.tilawa.lib.api import (
    DEFAULT_BASE_URL,
    Mp3QuranClient,
    Mp3QuranConnectionError,
    Mp3QuranResponseError,
)
from custom_components.tilawa.lib.models import Catalogue, RemoteFile

AUDIO = "https://cdn.mp3quran.net/audio/mahmoud-husary/r1/018.mp3"


def test_catalogue_from_fixtures(catalogue: Catalogue) -> None:
    assert set(catalogue.reciters) == {100, 102, 118, 123, 21203}
    assert len(catalogue.suwar) == 114
    assert len(catalogue.riwayat) == 20
    assert len(catalogue.moshaf_types) == 27

    hussary = catalogue.reciters[118]
    assert hussary.name_ar == "محمود خليل الحصري"
    assert hussary.name_en == "Mahmoud Khalil Al-Hussary"
    assert [m.id for m in hussary.moshafs] == [118, 119, 120, 269, 270]
    assert catalogue.moshafs[119].riwaya_id == 22
    assert catalogue.moshafs[119].type_id == 222

    partial = catalogue.moshafs[103]
    assert len(partial.surahs) == 38
    assert 78 in partial.surahs
    assert 2 not in partial.surahs

    assert catalogue.suwar[18].name_en == "Al-Kahf"  # trailing space stripped
    assert catalogue.suwar[36].name_en == "Ya-Sin"  # soft hyphen replaced
    assert catalogue.suwar[2].makki is False
    assert catalogue.moshaf_types[120].riwaya_id == 1
    assert catalogue.moshaf_types[120].style_id == 20


def test_file_url(catalogue: Catalogue) -> None:
    moshaf = catalogue.moshafs[118]
    assert moshaf.file_url(18) == AUDIO
    no_slash = replace(moshaf, server="https://example.net/x")
    assert no_slash.file_url(1) == "https://example.net/x/001.mp3"


def test_catalogue_roundtrip(catalogue: Catalogue) -> None:
    assert Catalogue.from_dict(catalogue.to_dict()) == catalogue


async def test_client_fetches_and_merges(
    payloads: dict[tuple[str, str], dict[str, Any]],
) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{DEFAULT_BASE_URL}/languages", payload={"language": []})
        for (path, lang), payload in payloads.items():
            mocked.get(f"{DEFAULT_BASE_URL}/{path}?language={lang}", payload=payload)
        async with aiohttp.ClientSession() as session:
            client = Mp3QuranClient(session)
            await client.async_ping()
            catalogue = await client.async_fetch_catalogue()
    assert len(catalogue.reciters) == 5
    assert catalogue.reciters[123].name_en == "Mishary Alafasi"


async def test_client_maps_errors() -> None:
    with aioresponses() as mocked:
        mocked.get(
            f"{DEFAULT_BASE_URL}/languages",
            exception=aiohttp.ClientConnectionError("boom"),
        )
        mocked.get(f"{DEFAULT_BASE_URL}/languages", status=500)
        mocked.get(f"{DEFAULT_BASE_URL}/languages", body="not json")
        async with aiohttp.ClientSession() as session:
            client = Mp3QuranClient(session)
            with pytest.raises(Mp3QuranConnectionError):
                await client.async_ping()
            with pytest.raises(Mp3QuranResponseError):
                await client.async_ping()
            with pytest.raises(Mp3QuranResponseError):
                await client.async_ping()


async def test_head() -> None:
    moved = "https://cdn.mp3quran.net/audio/new-slug/r1/018.mp3"
    other = "https://cdn.mp3quran.net/audio/muhammad-minshawi/r3/018.mp3"
    with aioresponses() as mocked:
        mocked.head(AUDIO, status=200, headers={"Content-Length": "123", "ETag": '"e"'})
        mocked.head(AUDIO, status=301, headers={"Location": moved})
        mocked.head(moved, status=200, headers={"Content-Length": "5"})
        mocked.head(AUDIO, status=302, headers={"Location": other})
        mocked.head(AUDIO, status=404)
        async with aiohttp.ClientSession() as session:
            client = Mp3QuranClient(session)
            assert await client.async_head(AUDIO) == RemoteFile(123, '"e"', None)
            assert (await client.async_head(AUDIO)).size == 5
            with pytest.raises(Mp3QuranResponseError):
                await client.async_head(AUDIO)
            with pytest.raises(Mp3QuranResponseError):
                await client.async_head(AUDIO)
