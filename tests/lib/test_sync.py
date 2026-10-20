"""End-to-end tests of the sync engine against a mocked CDN."""

import asyncio
from collections.abc import Callable
from pathlib import Path
import shutil

import aiohttp
from aioresponses import aioresponses
from mutagen.id3 import ID3
import pytest

from custom_components.tilawa.lib import sync as sync_module
from custom_components.tilawa.lib.api import Mp3QuranClient
from custom_components.tilawa.lib.downloader import Downloader
from custom_components.tilawa.lib.library import LibraryIndex, build_plan
from custom_components.tilawa.lib.models import (
    Catalogue,
    NamingOptions,
    Selection,
    SyncState,
    TrackIdentity,
)
from custom_components.tilawa.lib.sync import InsufficientSpace, SyncEngine
from custom_components.tilawa.lib.tagger import read_identity
from tests.conftest import MP3_FRAME, run_inline

AUDIO = MP3_FRAME * 30
SELECTION = Selection(118, 118, frozenset({1, 114}))
AR = NamingOptions()
EN = NamingOptions(names_language="eng", title_format="number_en")


def _mock_cdn(mocked: aioresponses, catalogue: Catalogue, *, status: int = 200) -> None:
    moshaf = catalogue.moshafs[118]
    for surah in (1, 114):
        url = moshaf.file_url(surah)
        headers = {"Content-Length": str(len(AUDIO)), "ETag": '"e"'}
        mocked.head(url, status=200, headers=headers)
        if status == 200:
            mocked.get(url, status=200, body=AUDIO, headers=headers)
        else:
            mocked.get(
                url,
                status=status,
                headers={"Location": "https://cdn.mp3quran.net/audio/x/r1/001.mp3"},
            )


def _engine(
    session: aiohttp.ClientSession,
    root: Path,
    index: LibraryIndex,
    states: list[SyncState],
) -> SyncEngine:
    return SyncEngine(
        client=Mp3QuranClient(session),
        downloader=Downloader(session, run_blocking=run_inline, max_retries=0),
        root=root,
        index=index,
        run_blocking=run_inline,
        on_progress=lambda progress: states.append(progress.state),
    )


async def test_sync_retag_delete_cycle(
    tmp_path: Path, catalogue: Catalogue, make_mp3: Callable[..., bytes]
) -> None:
    root = tmp_path / "Quran"
    index = LibraryIndex()
    states: list[SyncState] = []
    with aioresponses() as mocked:
        _mock_cdn(mocked, catalogue)
        async with aiohttp.ClientSession() as session:
            engine = _engine(session, root, index, states)
            plan = build_plan(catalogue, [SELECTION], AR, index)
            assert len(plan.downloads) == 2
            assert await engine.async_estimate(plan) == 2 * len(AUDIO)
            result = await engine.async_run(plan, asyncio.Event())

            assert result.success
            assert result.processed == 2
            assert result.bytes_downloaded == 2 * len(AUDIO)
            album_dir = root / "محمود خليل الحصري" / "حفص – مرتل"
            fatiha = album_dir / "001 الفاتحة.mp3"
            assert fatiha.is_file()
            assert (album_dir / "114 الناس.mp3").is_file()
            assert not list(root.rglob("*.part"))
            assert read_identity(fatiha) == TrackIdentity(118, 118, 1, '"e"')
            assert ID3(fatiha)["TALB"].text == ["حفص – مرتل"]
            assert len(index) == 2
            assert index.total_bytes > 2 * len(AUDIO)
            assert states[0] == SyncState.SYNCING
            assert states[-1] == SyncState.IDLE

            existing = await engine.async_existing_keys()
            assert build_plan(
                catalogue, [SELECTION], AR, index, existing_keys=existing
            ).is_empty

            # Switching the display language renames and retags without downloading.
            result = await engine.async_retag(
                catalogue, [SELECTION], EN, asyncio.Event()
            )
            assert result.success
            assert result.processed == 2
            new_dir = root / "Mahmoud Khalil Al-Hussary" / "Hafs – Murattal"
            moved = new_dir / "001 Al-Fatihah.mp3"
            assert moved.is_file()
            assert not fatiha.exists()
            assert not (root / "محمود خليل الحصري").exists()  # pruned
            assert ID3(moved)["TIT2"].text == ["001 Al-Fatihah"]
            assert read_identity(moved) == TrackIdentity(118, 118, 1, '"e"')
            assert index.get("118:118:1") is not None
            assert (
                index.get("118:118:1").relative_path
                == "Mahmoud Khalil Al-Hussary/Hafs – Murattal/001 Al-Fatihah.mp3"
            )  # type: ignore[union-attr]

            # Deleting a selection only touches files that carry our identity.
            foreign = new_dir / "foreign.mp3"
            make_mp3(foreign, legacy_tags=True)
            deleted = await engine.async_delete_selection("118:118")
            assert deleted == 2
            assert foreign.is_file()
            assert not moved.exists()
            assert len(index) == 0


async def test_refused_redirect_counts_as_failure(
    tmp_path: Path, catalogue: Catalogue
) -> None:
    root = tmp_path / "Quran"
    index = LibraryIndex()
    states: list[SyncState] = []
    with aioresponses() as mocked:
        _mock_cdn(mocked, catalogue, status=302)
        async with aiohttp.ClientSession() as session:
            engine = _engine(session, root, index, states)
            plan = build_plan(catalogue, [SELECTION], AR, index)
            result = await engine.async_run(plan, asyncio.Event())
    assert not result.success
    assert result.failed == 2
    assert len(result.errors) == 2
    assert states[-1] == SyncState.ERROR
    assert len(index) == 0
    assert not list(root.rglob("*.mp3"))


async def test_cancelled_before_start_downloads_nothing(
    tmp_path: Path, catalogue: Catalogue
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    with aioresponses() as mocked:
        _mock_cdn(mocked, catalogue)
        async with aiohttp.ClientSession() as session:
            engine = _engine(session, tmp_path, LibraryIndex(), [])
            plan = build_plan(catalogue, [SELECTION], AR, engine.index)
            result = await engine.async_run(plan, cancel)
    assert result.cancelled
    assert result.processed == 0
    assert not list(tmp_path.rglob("*.mp3"))


async def test_insufficient_space_aborts(
    tmp_path: Path, catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        sync_module.shutil, "disk_usage", lambda _path: usage._replace(free=1024)
    )
    with aioresponses() as mocked:
        _mock_cdn(mocked, catalogue)
        async with aiohttp.ClientSession() as session:
            engine = _engine(session, tmp_path, LibraryIndex(), [])
            plan = build_plan(catalogue, [SELECTION], AR, engine.index)
            await engine.async_estimate(plan)
            with pytest.raises(InsufficientSpace) as excinfo:
                await engine.async_run(plan, asyncio.Event())
    assert excinfo.value.free == 1024
    assert excinfo.value.needed > 2 * len(AUDIO)


async def test_adopt_indexes_files_with_our_tags(
    tmp_path: Path, catalogue: Catalogue, make_mp3: Callable[..., bytes]
) -> None:
    from custom_components.tilawa.lib.library import desired_tracks  # noqa: PLC0415
    from custom_components.tilawa.lib.tagger import write_tags  # noqa: PLC0415

    tracks, _ = desired_tracks(catalogue, [SELECTION], AR)
    spec = tracks["118:118:1"]
    path = tmp_path / "somewhere" / "001.mp3"
    make_mp3(path)
    write_tags(path, spec.tags)
    make_mp3(tmp_path / "foreign.mp3", legacy_tags=True)

    async with aiohttp.ClientSession() as session:
        engine = _engine(session, tmp_path, LibraryIndex(), [])
        assert await engine.async_adopt() == 1
        assert await engine.async_adopt() == 0
    adopted = engine.index.get("118:118:1")
    assert adopted is not None
    assert adopted.relative_path == "somewhere/001.mp3"
    assert adopted.naming_fingerprint == ""
    plan = build_plan(
        catalogue, [SELECTION], AR, engine.index, existing_keys={"118:118:1"}
    )
    assert [indexed.key for indexed, _ in plan.retags] == ["118:118:1"]
    assert [spec.key for spec in plan.downloads] == ["118:118:114"]
