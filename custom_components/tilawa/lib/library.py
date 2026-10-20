"""The library index and the pure plan builder (desired set vs. what we have)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence, Set as AbstractSet
from types import MappingProxyType
from typing import Any, Self

from .models import (
    Catalogue,
    IndexedFile,
    NamingOptions,
    RemoteFile,
    Selection,
    SyncPlan,
    TrackSpec,
    selection_key_of_track,
    split_track_key,
)
from .naming import album_names_for_reciter, build_track


class LibraryIndex:
    """In-memory record of every file Tilawa created. No I/O of its own."""

    def __init__(self, files: Mapping[str, IndexedFile] | None = None) -> None:
        """Create an index, optionally pre-populated."""
        self._files: dict[str, IndexedFile] = dict(files or {})

    @property
    def files(self) -> Mapping[str, IndexedFile]:
        """Read-only view of the indexed files by track key."""
        return MappingProxyType(self._files)

    def __len__(self) -> int:
        """Return the number of indexed files."""
        return len(self._files)

    def __contains__(self, key: object) -> bool:
        """Return True if the track key is indexed."""
        return key in self._files

    def __iter__(self) -> Iterator[IndexedFile]:
        """Iterate over indexed files."""
        return iter(self._files.values())

    def get(self, key: str) -> IndexedFile | None:
        """Return an indexed file by key."""
        return self._files.get(key)

    def add(self, file: IndexedFile) -> None:
        """Insert or replace an indexed file."""
        self._files[file.key] = file

    def remove(self, key: str) -> IndexedFile | None:
        """Drop a key from the index and return what was there."""
        return self._files.pop(key, None)

    def keys_for_selection(self, selection_key: str) -> list[str]:
        """Return the track keys belonging to a selection."""
        return [
            key for key in self._files if selection_key_of_track(key) == selection_key
        ]

    @property
    def total_bytes(self) -> int:
        """Return the sum of indexed file sizes."""
        return sum(file.size for file in self._files.values())

    def reciter_ids(self) -> set[int]:
        """Return the distinct reciter ids present in the index."""
        return {split_track_key(key)[0] for key in self._files}

    def to_dict(self) -> dict[str, Any]:
        """Serialise."""
        return {"files": [file.to_dict() for file in self._files.values()]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialise."""
        files = [IndexedFile.from_dict(item) for item in data.get("files", [])]
        return cls({file.key: file for file in files})


def desired_tracks(
    catalogue: Catalogue,
    selections: Sequence[Selection],
    options: NamingOptions,
) -> tuple[dict[str, TrackSpec], list[Selection]]:
    """Return every track the selections ask for, plus selections the catalogue lacks.

    Album names are disambiguated per reciter across all of that reciter's selected
    versions, so two versions never share an album name.
    """
    by_reciter: dict[int, list[Selection]] = {}
    for selection in selections:
        by_reciter.setdefault(selection.reciter_id, []).append(selection)

    tracks: dict[str, TrackSpec] = {}
    missing: list[Selection] = []
    for reciter_id, group in by_reciter.items():
        reciter = catalogue.reciters.get(reciter_id)
        valid: list[tuple[Selection, Any]] = []
        for selection in group:
            moshaf = catalogue.moshafs.get(selection.moshaf_id)
            if reciter is None or moshaf is None or moshaf.reciter_id != reciter_id:
                missing.append(selection)
                continue
            valid.append((selection, moshaf))
        if reciter is None or not valid:
            continue
        moshafs = [moshaf for _, moshaf in valid]
        albums = album_names_for_reciter(moshafs, catalogue, options.names_language)
        albums_en = album_names_for_reciter(moshafs, catalogue, "eng")
        for selection, moshaf in valid:
            for number in selection.wanted(moshaf.surahs):
                surah = catalogue.suwar.get(number)
                if surah is None:
                    continue
                spec = build_track(
                    reciter,
                    moshaf,
                    surah,
                    options,
                    album=albums[moshaf.id],
                    album_sort=albums_en[moshaf.id],
                )
                tracks[spec.key] = spec
    return tracks, missing


def build_plan(
    catalogue: Catalogue,
    selections: Sequence[Selection],
    options: NamingOptions,
    index: LibraryIndex,
    *,
    existing_keys: AbstractSet[str] | None = None,
    redownload_changed: bool = False,
    remote: Mapping[str, RemoteFile] | None = None,
) -> SyncPlan:
    """Diff the desired set against the index.

    ``existing_keys`` is the set of indexed keys whose file is really on disk (the
    caller checks that in an executor); ``None`` trusts the index. ``remote`` holds
    HEAD results used for ``redownload_changed``.
    """
    desired, missing = desired_tracks(catalogue, selections, options)
    plan = SyncPlan(missing_selections=missing)
    for key, spec in desired.items():
        indexed = index.get(key)
        on_disk = indexed is not None and (
            existing_keys is None or key in existing_keys
        )
        if indexed is None or not on_disk:
            plan.downloads.append(spec)
            continue
        if (
            indexed.naming_fingerprint != spec.naming_fingerprint
            or indexed.relative_path != spec.relative_path
        ):
            plan.retags.append((indexed, spec))
        if redownload_changed and remote is not None:
            head = remote.get(key)
            if head is not None and head.etag and head.etag != indexed.source_etag:
                plan.downloads.append(spec)
    plan.orphans = [file for key, file in index.files.items() if key not in desired]
    if remote:
        plan.remote.update(remote)
    return plan
