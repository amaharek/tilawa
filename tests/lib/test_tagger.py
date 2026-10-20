"""Tests for ID3 writing and reading."""

from collections.abc import Callable
from pathlib import Path

from mutagen.id3 import ID3

from custom_components.tilawa.lib.models import TrackIdentity, TrackTags
from custom_components.tilawa.lib.tagger import read_identity, write_tags

TAGS = TrackTags(
    artist="محمود خليل الحصري",
    album_artist="محمود خليل الحصري",
    album="حفص – مرتل",
    title="018 الكهف",
    track=(18, 114),
    sort_artist="Mahmoud Khalil Al-Hussary",
    sort_album_artist="Mahmoud Khalil Al-Hussary",
    sort_album="Hafs – Murattal",
    sort_title="018 Al-Kahf",
    reciter_id=118,
    moshaf_id=118,
    surah=18,
    source_etag='"abc"',
)


def test_write_replaces_everything_and_keeps_audio(
    tmp_path: Path, make_mp3: Callable[..., bytes]
) -> None:
    path = tmp_path / "018.mp3"
    audio = make_mp3(path, legacy_tags=True)
    assert ID3(path).getall("APIC")

    write_tags(path, TAGS)

    id3 = ID3(path)
    assert id3.version[:2] == (2, 4)
    assert id3["TPE1"].text == ["محمود خليل الحصري"]
    assert id3["TPE2"].text == ["محمود خليل الحصري"]
    assert id3["TALB"].text == ["حفص – مرتل"]
    assert id3["TIT2"].text == ["018 الكهف"]
    assert id3["TRCK"].text == ["18/114"]
    assert id3["TPOS"].text == ["1/1"]
    assert id3["TCON"].text == ["Quran"]
    assert id3["TSOP"].text == ["Mahmoud Khalil Al-Hussary"]
    assert id3["TSO2"].text == ["Mahmoud Khalil Al-Hussary"]
    assert id3["TSOA"].text == ["Hafs – Murattal"]
    assert id3["TSOT"].text == ["018 Al-Kahf"]
    assert id3["TXXX:TILAWA_RECITER_ID"].text == ["118"]
    assert id3["TXXX:TILAWA_SOURCE_ETAG"].text == ['"abc"']
    assert not id3.getall("APIC")
    data = path.read_bytes()
    assert data.endswith(audio)  # audio untouched, no ID3v1 trailer
    assert read_identity(path) == TrackIdentity(118, 118, 18, '"abc"')


def test_read_identity_ignores_foreign_files(
    tmp_path: Path, make_mp3: Callable[..., bytes]
) -> None:
    tagged = tmp_path / "foreign.mp3"
    make_mp3(tagged, legacy_tags=True)
    assert read_identity(tagged) is None
    bare = tmp_path / "bare.mp3"
    make_mp3(bare)
    assert read_identity(bare) is None
