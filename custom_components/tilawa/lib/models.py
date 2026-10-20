"""Data model for the Tilawa core library.

Pure Python: no Home Assistant imports. Everything that crosses a boundary
(storage, diagnostics) has explicit ``to_dict`` / ``from_dict`` helpers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

type Language = Literal["ar", "eng"]
type TitleFormat = Literal["number_ar", "number_en", "number_both"]
type NumberSeparator = Literal["space", "hyphen", "spaced_hyphen"]

LANGUAGES: tuple[Language, ...] = ("ar", "eng")
TITLE_FORMATS: tuple[TitleFormat, ...] = ("number_ar", "number_en", "number_both")
NUMBER_SEPARATORS: tuple[NumberSeparator, ...] = ("space", "hyphen", "spaced_hyphen")
SURAH_COUNT = 114
ALL_SURAHS: frozenset[int] = frozenset(range(1, SURAH_COUNT + 1))
GENRE = "Quran"


class SyncState(StrEnum):
    """Lifecycle state reported by the sync engine."""

    IDLE = "idle"
    SYNCING = "syncing"
    RETAGGING = "retagging"
    MOVING = "moving"
    ERROR = "error"


class JobKind(StrEnum):
    """Kind of background job."""

    SYNC = "sync"
    RETAG = "retag"
    MOVE = "move"


def selection_key(reciter_id: int, moshaf_id: int) -> str:
    """Return the stable key of a reciter/version selection."""
    return f"{reciter_id}:{moshaf_id}"


def track_key(reciter_id: int, moshaf_id: int, surah: int) -> str:
    """Return the stable key of one downloaded surah."""
    return f"{reciter_id}:{moshaf_id}:{surah}"


def split_track_key(key: str) -> tuple[int, int, int]:
    """Split a track key into (reciter_id, moshaf_id, surah)."""
    reciter_id, moshaf_id, surah = (int(part) for part in key.split(":"))
    return reciter_id, moshaf_id, surah


def selection_key_of_track(key: str) -> str:
    """Return the selection key a track key belongs to."""
    return key.rsplit(":", 1)[0]


def _pick(language: Language, ar: str, en: str) -> str:
    return ar if language == "ar" else en


@dataclass(frozen=True, slots=True)
class Surah:
    """One of the 114 surahs."""

    number: int
    name_ar: str
    name_en: str
    makki: bool
    start_page: int
    end_page: int

    def name(self, language: Language) -> str:
        """Return the display name in the given language."""
        return _pick(language, self.name_ar, self.name_en)

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        return cls(**data)


@dataclass(frozen=True, slots=True)
class Riwaya:
    """A riwaya (transmission) as listed by ``/riwayat``."""

    id: int
    name_ar: str
    name_en: str

    def name(self, language: Language) -> str:
        """Return the display name in the given language."""
        return _pick(language, self.name_ar, self.name_en)

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        return cls(**data)


@dataclass(frozen=True, slots=True)
class MoshafType:
    """A row of the undocumented ``/moshaf`` table: riwaya x recitation style."""

    id: int
    riwaya_id: int
    style_id: int
    name_ar: str
    name_en: str

    def name(self, language: Language) -> str:
        """Return the display name in the given language."""
        return _pick(language, self.name_ar, self.name_en)

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        return cls(**data)


@dataclass(frozen=True, slots=True)
class Moshaf:
    """One recorded version (riwaya + style) of a reciter."""

    id: int
    reciter_id: int
    name_ar: str
    name_en: str
    riwaya_id: int
    type_id: int
    server: str
    surahs: frozenset[int]

    def name(self, language: Language) -> str:
        """Return the display name in the given language."""
        return _pick(language, self.name_ar, self.name_en)

    def file_url(self, surah: int) -> str:
        """Return the audio URL of a surah (``{server}{NNN}.mp3``)."""
        return f"{self.server.rstrip('/')}/{surah:03d}.mp3"

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        data = asdict(self)
        data["surahs"] = sorted(self.surahs)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        return cls(
            id=int(data["id"]),
            reciter_id=int(data["reciter_id"]),
            name_ar=data["name_ar"],
            name_en=data["name_en"],
            riwaya_id=int(data["riwaya_id"]),
            type_id=int(data["type_id"]),
            server=data["server"],
            surahs=frozenset(int(n) for n in data["surahs"]),
        )


@dataclass(frozen=True, slots=True)
class Reciter:
    """A reciter and the versions available for them."""

    id: int
    name_ar: str
    name_en: str
    moshafs: tuple[Moshaf, ...]

    def name(self, language: Language) -> str:
        """Return the display name in the given language."""
        return _pick(language, self.name_ar, self.name_en)

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return {
            "id": self.id,
            "name_ar": self.name_ar,
            "name_en": self.name_en,
            "moshafs": [m.to_dict() for m in self.moshafs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        return cls(
            id=int(data["id"]),
            name_ar=data["name_ar"],
            name_en=data["name_en"],
            moshafs=tuple(Moshaf.from_dict(m) for m in data["moshafs"]),
        )


@dataclass(frozen=True, slots=True)
class Catalogue:
    """Everything fetched from the API, merged across languages."""

    fetched_at: datetime
    reciters: Mapping[int, Reciter]
    suwar: Mapping[int, Surah]
    riwayat: Mapping[int, Riwaya]
    moshaf_types: Mapping[int, MoshafType]
    moshafs: Mapping[int, Moshaf] = field(init=False)

    def __post_init__(self) -> None:
        """Index every moshaf by id for direct lookups."""
        moshafs = {m.id: m for r in self.reciters.values() for m in r.moshafs}
        object.__setattr__(self, "moshafs", moshafs)

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "reciters": [r.to_dict() for r in self.reciters.values()],
            "suwar": [s.to_dict() for s in self.suwar.values()],
            "riwayat": [r.to_dict() for r in self.riwayat.values()],
            "moshaf_types": [t.to_dict() for t in self.moshaf_types.values()],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        reciters = [Reciter.from_dict(r) for r in data["reciters"]]
        suwar = [Surah.from_dict(s) for s in data["suwar"]]
        riwayat = [Riwaya.from_dict(r) for r in data["riwayat"]]
        types = [MoshafType.from_dict(t) for t in data["moshaf_types"]]
        return cls(
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
            reciters={r.id: r for r in reciters},
            suwar={s.number: s for s in suwar},
            riwayat={r.id: r for r in riwayat},
            moshaf_types={t.id: t for t in types},
        )


@dataclass(frozen=True, slots=True)
class Selection:
    """A reciter/version the user wants, optionally limited to some surahs."""

    reciter_id: int
    moshaf_id: int
    surahs: frozenset[int] | None = None

    @property
    def key(self) -> str:
        """Return the stable selection key."""
        return selection_key(self.reciter_id, self.moshaf_id)

    def wanted(self, available: frozenset[int]) -> list[int]:
        """Return the sorted surah numbers to keep for a moshaf's available set."""
        wanted = available if self.surahs is None else available & self.surahs
        return sorted(wanted)

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return {
            "reciter_id": self.reciter_id,
            "moshaf_id": self.moshaf_id,
            "surahs": None if self.surahs is None else sorted(self.surahs),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        surahs = data.get("surahs")
        return cls(
            reciter_id=int(data["reciter_id"]),
            moshaf_id=int(data["moshaf_id"]),
            surahs=None if surahs is None else frozenset(int(n) for n in surahs),
        )


@dataclass(frozen=True, slots=True)
class NamingOptions:
    """User-facing naming choices that drive tags and paths."""

    names_language: Language = "ar"
    title_format: TitleFormat = "number_ar"
    number_separator: NumberSeparator = "space"


@dataclass(frozen=True, slots=True)
class TrackIdentity:
    """What the ``TXXX:TILAWA_*`` frames of a file say about it."""

    reciter_id: int
    moshaf_id: int
    surah: int
    source_etag: str | None = None

    @property
    def key(self) -> str:
        """Return the track key."""
        return track_key(self.reciter_id, self.moshaf_id, self.surah)


@dataclass(frozen=True, slots=True)
class TrackTags:
    """Every tag written to a file."""

    artist: str
    album_artist: str
    album: str
    title: str
    track: tuple[int, int]
    sort_artist: str
    sort_album_artist: str
    sort_album: str
    sort_title: str
    reciter_id: int
    moshaf_id: int
    surah: int
    disc: tuple[int, int] = (1, 1)
    genre: str = GENRE
    source_etag: str | None = None

    @property
    def identity(self) -> TrackIdentity:
        """Return the identity part of the tags."""
        return TrackIdentity(
            self.reciter_id, self.moshaf_id, self.surah, self.source_etag
        )


@dataclass(frozen=True, slots=True)
class TrackSpec:
    """Where a surah should live and how it should be tagged."""

    key: str
    url: str
    relative_path: str
    tags: TrackTags
    surah: int
    naming_fingerprint: str


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """What a HEAD (or a finished GET) told us about a file."""

    size: int | None
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class IndexedFile:
    """A file the integration created and tracks."""

    key: str
    relative_path: str
    size: int
    source_etag: str | None
    naming_fingerprint: str
    downloaded_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        data = asdict(self)
        data["downloaded_at"] = self.downloaded_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        return cls(
            key=data["key"],
            relative_path=data["relative_path"],
            size=int(data["size"]),
            source_etag=data.get("source_etag"),
            naming_fingerprint=data.get("naming_fingerprint", ""),
            downloaded_at=datetime.fromisoformat(data["downloaded_at"]),
        )


@dataclass(slots=True)
class SyncPlan:
    """The work a sync has to do, computed without touching the network."""

    downloads: list[TrackSpec] = field(default_factory=list)
    retags: list[tuple[IndexedFile, TrackSpec]] = field(default_factory=list)
    orphans: list[IndexedFile] = field(default_factory=list)
    missing_selections: list[Selection] = field(default_factory=list)
    remote: dict[str, RemoteFile] = field(default_factory=dict)
    estimated_bytes: int | None = None

    @property
    def is_empty(self) -> bool:
        """Return True when nothing needs downloading or retagging."""
        return not self.downloads and not self.retags


@dataclass(slots=True)
class SyncProgress:
    """Live progress of the running job; mutated in place and emitted."""

    state: SyncState = SyncState.IDLE
    kind: JobKind | None = None
    total: int = 0
    done: int = 0
    failed: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    current_key: str | None = None
    started_at: datetime | None = None
    error: str | None = None

    @property
    def percent(self) -> float:
        """Return completion as 0-100, preferring bytes when known."""
        if self.bytes_total > 0:
            return min(100.0, 100.0 * self.bytes_done / self.bytes_total)
        if self.total > 0:
            return min(100.0, 100.0 * self.done / self.total)
        return 0.0


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Outcome of a finished job."""

    kind: JobKind
    started_at: datetime
    finished_at: datetime
    processed: int
    failed: int
    cancelled: bool
    bytes_downloaded: int = 0
    errors: Sequence[str] = ()

    @property
    def success(self) -> bool:
        """Return True when the job completed without failures."""
        return not self.cancelled and self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return {
            "kind": self.kind.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "processed": self.processed,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "bytes_downloaded": self.bytes_downloaded,
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        return cls(
            kind=JobKind(data["kind"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]),
            processed=int(data["processed"]),
            failed=int(data["failed"]),
            cancelled=bool(data["cancelled"]),
            bytes_downloaded=int(data.get("bytes_downloaded", 0)),
            errors=tuple(data.get("errors", ())),
        )
