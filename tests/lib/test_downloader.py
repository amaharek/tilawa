"""Tests for the resumable downloader."""

from pathlib import Path

import aiohttp
from aioresponses import aioresponses
import pytest
from yarl import URL

from custom_components.tilawa.lib.downloader import (
    Downloader,
    DownloadError,
    RedirectRefused,
    TokenBucket,
)
from custom_components.tilawa.lib.models import RemoteFile
from tests.conftest import MP3_FRAME, run_inline

AUDIO_URL = "https://cdn.mp3quran.net/audio/mahmoud-husary/r1/018.mp3"
MOVED_URL = "https://cdn.mp3quran.net/audio/mahmoud-husary-new/r1/018.mp3"
OTHER_URL = "https://cdn.mp3quran.net/audio/muhammad-minshawi/r3/018.mp3"
OTHER_SURAH_URL = "https://cdn.mp3quran.net/audio/mahmoud-husary/r1/002.mp3"
DATA = MP3_FRAME * 40


def _headers(body: bytes, **extra: str) -> dict[str, str]:
    return {"Content-Length": str(len(body)), "ETag": '"e1"', **extra}


async def test_full_download(tmp_path: Path) -> None:
    part = tmp_path / "018.mp3.part"
    with aioresponses() as mocked:
        mocked.get(AUDIO_URL, status=200, body=DATA, headers=_headers(DATA))
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(session, run_blocking=run_inline, max_retries=0)
            seen: list[int] = []
            result = await downloader.async_download(
                AUDIO_URL, part, on_progress=seen.append
            )
    assert result == RemoteFile(len(DATA), '"e1"', None)
    assert part.read_bytes() == DATA
    assert sum(seen) == len(DATA)


async def test_resume_sends_range_and_if_range(tmp_path: Path) -> None:
    part = tmp_path / "018.mp3.part"
    part.write_bytes(DATA[:1000])
    rest = DATA[1000:]
    with aioresponses() as mocked:
        mocked.get(
            AUDIO_URL,
            status=206,
            body=rest,
            headers=_headers(
                rest, **{"Content-Range": f"bytes 1000-{len(DATA) - 1}/{len(DATA)}"}
            ),
        )
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(session, run_blocking=run_inline, max_retries=0)
            result = await downloader.async_download(
                AUDIO_URL, part, expected=RemoteFile(len(DATA), '"e1"')
            )
        request = mocked.requests[("GET", URL(AUDIO_URL))][0]
    assert result.size == len(DATA)
    assert part.read_bytes() == DATA
    assert request.kwargs["headers"]["Range"] == "bytes=1000-"
    assert request.kwargs["headers"]["If-Range"] == '"e1"'


async def test_changed_upstream_restarts_from_scratch(tmp_path: Path) -> None:
    part = tmp_path / "018.mp3.part"
    part.write_bytes(b"old partial content")
    with aioresponses() as mocked:
        mocked.get(AUDIO_URL, status=200, body=DATA, headers=_headers(DATA))
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(session, run_blocking=run_inline, max_retries=0)
            await downloader.async_download(AUDIO_URL, part)
    assert part.read_bytes() == DATA


async def test_temporary_redirect_is_refused(tmp_path: Path) -> None:
    with aioresponses() as mocked:
        mocked.get(AUDIO_URL, status=302, headers={"Location": OTHER_URL})
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(session, run_blocking=run_inline, max_retries=0)
            with pytest.raises(RedirectRefused):
                await downloader.async_download(AUDIO_URL, tmp_path / "x.part")
    assert not (tmp_path / "x.part").exists()


async def test_permanent_redirect_to_same_file_is_followed(tmp_path: Path) -> None:
    part = tmp_path / "018.mp3.part"
    with aioresponses() as mocked:
        mocked.get(AUDIO_URL, status=301, headers={"Location": MOVED_URL})
        mocked.get(MOVED_URL, status=200, body=DATA, headers=_headers(DATA))
        mocked.get(AUDIO_URL, status=301, headers={"Location": OTHER_SURAH_URL})
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(session, run_blocking=run_inline, max_retries=0)
            result = await downloader.async_download(AUDIO_URL, part)
            with pytest.raises(RedirectRefused):
                await downloader.async_download(AUDIO_URL, tmp_path / "y.part")
    assert result.size == len(DATA)
    assert part.read_bytes() == DATA


async def test_short_body_fails_after_retries(tmp_path: Path) -> None:
    part = tmp_path / "018.mp3.part"
    with aioresponses() as mocked:
        mocked.get(AUDIO_URL, status=200, body=DATA[:500], headers=_headers(DATA))
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(session, run_blocking=run_inline, max_retries=0)
            with pytest.raises(DownloadError):
                await downloader.async_download(AUDIO_URL, part)
    assert part.read_bytes() == DATA[:500]  # kept for a later resume


async def test_retries_with_backoff_then_succeeds(tmp_path: Path) -> None:
    part = tmp_path / "018.mp3.part"
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    with aioresponses() as mocked:
        mocked.get(AUDIO_URL, status=503)
        mocked.get(AUDIO_URL, exception=aiohttp.ClientConnectionError("reset"))
        mocked.get(AUDIO_URL, status=200, body=DATA, headers=_headers(DATA))
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(
                session, run_blocking=run_inline, max_retries=3, sleep=fake_sleep
            )
            result = await downloader.async_download(AUDIO_URL, part)
    assert result.size == len(DATA)
    assert len(delays) == 2
    assert delays[0] < delays[1]


async def test_not_found_is_permanent(tmp_path: Path) -> None:
    with aioresponses() as mocked:
        mocked.get(AUDIO_URL, status=404)
        async with aiohttp.ClientSession() as session:
            downloader = Downloader(session, run_blocking=run_inline, max_retries=3)
            with pytest.raises(DownloadError):
                await downloader.async_download(AUDIO_URL, tmp_path / "x.part")


async def test_token_bucket_sleeps_when_over_budget() -> None:
    clock = [0.0]
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)
        clock[0] += delay

    bucket = TokenBucket(1000, monotonic=lambda: clock[0], sleep=fake_sleep)
    await bucket.consume(500)
    assert slept == []
    await bucket.consume(1000)
    assert slept == [pytest.approx(0.5)]
