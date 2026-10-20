"""ID3 tagging with mutagen. All functions block and must run in an executor."""

from __future__ import annotations

from pathlib import Path

from mutagen.id3 import (
    ID3,
    TALB,
    TCON,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TSO2,
    TSOA,
    TSOP,
    TSOT,
    TXXX,
    Encoding,
    ID3NoHeaderError,
)

from .models import TrackIdentity, TrackTags

TXXX_RECITER_ID = "TILAWA_RECITER_ID"
TXXX_MOSHAF_ID = "TILAWA_MOSHAF_ID"
TXXX_SURAH = "TILAWA_SURAH"
TXXX_SOURCE_ETAG = "TILAWA_SOURCE_ETAG"


def _txxx(desc: str, value: str) -> TXXX:
    return TXXX(encoding=Encoding.UTF8, desc=desc, text=[value])


def write_tags(path: Path, tags: TrackTags) -> None:
    """Replace every tag on ``path`` with ours (ID3v2.4, UTF-8, no ID3v1)."""
    try:
        existing = ID3(path)
    except ID3NoHeaderError:
        pass
    else:
        existing.delete(path)

    id3 = ID3()
    enc = Encoding.UTF8
    id3.add(TPE1(encoding=enc, text=[tags.artist]))
    id3.add(TPE2(encoding=enc, text=[tags.album_artist]))
    id3.add(TALB(encoding=enc, text=[tags.album]))
    id3.add(TIT2(encoding=enc, text=[tags.title]))
    id3.add(TRCK(encoding=enc, text=[f"{tags.track[0]}/{tags.track[1]}"]))
    id3.add(TPOS(encoding=enc, text=[f"{tags.disc[0]}/{tags.disc[1]}"]))
    id3.add(TCON(encoding=enc, text=[tags.genre]))
    id3.add(TSOP(encoding=enc, text=[tags.sort_artist]))
    id3.add(TSO2(encoding=enc, text=[tags.sort_album_artist]))
    id3.add(TSOA(encoding=enc, text=[tags.sort_album]))
    id3.add(TSOT(encoding=enc, text=[tags.sort_title]))
    id3.add(_txxx(TXXX_RECITER_ID, str(tags.reciter_id)))
    id3.add(_txxx(TXXX_MOSHAF_ID, str(tags.moshaf_id)))
    id3.add(_txxx(TXXX_SURAH, str(tags.surah)))
    if tags.source_etag:
        id3.add(_txxx(TXXX_SOURCE_ETAG, tags.source_etag))
    id3.save(path, v1=0, v2_version=4)


def _txxx_text(id3: ID3, desc: str) -> str | None:
    frame = id3.get(f"TXXX:{desc}")
    if frame is None or not frame.text:
        return None
    return str(frame.text[0])


def read_identity(path: Path) -> TrackIdentity | None:
    """Return the Tilawa identity stored in a file, or None if it is not ours."""
    try:
        id3 = ID3(path)
    except ID3NoHeaderError:
        return None
    reciter = _txxx_text(id3, TXXX_RECITER_ID)
    moshaf = _txxx_text(id3, TXXX_MOSHAF_ID)
    surah = _txxx_text(id3, TXXX_SURAH)
    if reciter is None or moshaf is None or surah is None:
        return None
    try:
        return TrackIdentity(
            reciter_id=int(reciter),
            moshaf_id=int(moshaf),
            surah=int(surah),
            source_etag=_txxx_text(id3, TXXX_SOURCE_ETAG),
        )
    except ValueError:
        return None
