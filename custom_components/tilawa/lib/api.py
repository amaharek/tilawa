"""Async client for the mp3quran.net v3 API.

The ``aiohttp.ClientSession`` is injected so Home Assistant can pass its shared
session. See ``docs/api-notes.md`` for what the endpoints really return.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
import logging
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .models import (
    LANGUAGES,
    Catalogue,
    Language,
    Moshaf,
    MoshafType,
    Reciter,
    RemoteFile,
    Riwaya,
    Surah,
)
from .naming import normalize

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.mp3quran.net/api/v3"
USER_AGENT = "Tilawa/0.1.0 (+https://github.com/amaharek/tilawa)"
PERMANENT_REDIRECTS = frozenset({301, 308})
TEMPORARY_REDIRECTS = frozenset({302, 303, 307})

type Payloads = Mapping[tuple[str, Language], Mapping[str, Any]]


class Mp3QuranError(Exception):
    """Base error of the client."""


class Mp3QuranConnectionError(Mp3QuranError):
    """The API or CDN could not be reached."""


class Mp3QuranResponseError(Mp3QuranError):
    """The API answered, but not with what we expected."""


def same_file_redirect(url: str, location: str | None) -> str | None:
    """Return the absolute redirect target if it points at the same ``NNN.mp3``."""
    if not location:
        return None
    target = urljoin(url, location)
    basename = url.rsplit("/", 1)[-1]
    return target if target.rsplit("/", 1)[-1] == basename else None


class Mp3QuranClient:
    """Thin async wrapper around the catalogue endpoints and HEAD requests."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = USER_AGENT,
        timeout: float = 30.0,
    ) -> None:
        """Initialise with an injected session."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get_json(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        url = f"{self._base_url}/{path}"
        try:
            async with self._session.get(
                url, params=params, headers=self._headers, timeout=self._timeout
            ) as response:
                if response.status >= 400:
                    raise Mp3QuranResponseError(f"HTTP {response.status} for {url}")
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise Mp3QuranConnectionError(f"Cannot reach {url}: {err}") from err
        except ValueError as err:
            raise Mp3QuranResponseError(f"Invalid JSON from {url}") from err
        if not isinstance(data, dict):
            raise Mp3QuranResponseError(f"Unexpected payload from {url}")
        return data

    async def async_ping(self) -> None:
        """Raise ``Mp3QuranConnectionError`` if the API is unreachable."""
        await self._get_json("languages", {})

    async def async_fetch_catalogue(self, *, now: datetime | None = None) -> Catalogue:
        """Fetch reciters, suwar, riwayat and moshaf types in both languages."""
        keys = [
            (path, lang)
            for path in ("reciters", "suwar", "riwayat", "moshaf")
            for lang in LANGUAGES
        ]
        results = await asyncio.gather(
            *(self._get_json(path, {"language": lang}) for path, lang in keys)
        )
        payloads = dict(zip(keys, results, strict=True))
        return build_catalogue(payloads, fetched_at=now or datetime.now(UTC))

    async def async_head(self, url: str) -> RemoteFile:
        """HEAD an audio file; follows one same-file permanent redirect only."""
        target = url
        try:
            for _ in range(2):
                async with self._session.head(
                    target,
                    headers={"User-Agent": self._headers["User-Agent"]},
                    allow_redirects=False,
                    timeout=self._timeout,
                ) as response:
                    if response.status in PERMANENT_REDIRECTS:
                        redirected = same_file_redirect(
                            target, response.headers.get("Location")
                        )
                        if redirected is None:
                            raise Mp3QuranResponseError(
                                f"Refusing redirect of {target} to another file"
                            )
                        target = redirected
                        continue
                    if response.status != 200:
                        raise Mp3QuranResponseError(
                            f"HEAD {target} returned HTTP {response.status}"
                        )
                    length = response.headers.get("Content-Length")
                    return RemoteFile(
                        size=int(length) if length and length.isdigit() else None,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise Mp3QuranConnectionError(f"Cannot reach {target}: {err}") from err
        raise Mp3QuranResponseError(f"Too many redirects for {url}")


def _int(value: Any) -> int:
    return int(value)


def _by_language(payloads: Payloads, path: str, key: str) -> dict[Language, list[Any]]:
    out: dict[Language, list[Any]] = {}
    for lang in LANGUAGES:
        payload = payloads.get((path, lang))
        if payload is None:
            continue
        items = payload.get(key)
        if not isinstance(items, list):
            raise Mp3QuranResponseError(f"'{key}' missing in /{path}?language={lang}")
        out[lang] = items
    if not out:
        raise Mp3QuranResponseError(f"No data for /{path}")
    return out


def _names(
    rows: Mapping[Language, Mapping[int, Mapping[str, Any]]], item_id: int
) -> tuple[str, str]:
    ar = rows.get("ar", {}).get(item_id)
    en = rows.get("eng", {}).get(item_id)
    name_ar = normalize(str(ar["name"])) if ar else ""
    name_en = normalize(str(en["name"])) if en else ""
    return name_ar or name_en, name_en or name_ar


def _rows_by_id(
    items: Mapping[Language, list[Any]],
) -> dict[Language, dict[int, Mapping[str, Any]]]:
    try:
        return {
            lang: {_int(row["id"]): row for row in rows} for lang, rows in items.items()
        }
    except (KeyError, TypeError, ValueError) as err:
        raise Mp3QuranResponseError(f"Malformed catalogue row: {err}") from err


def build_catalogue(payloads: Payloads, *, fetched_at: datetime) -> Catalogue:
    """Merge the raw API payloads of both languages into a :class:`Catalogue`."""
    try:
        return _build_catalogue(payloads, fetched_at)
    except (KeyError, TypeError, ValueError) as err:
        raise Mp3QuranResponseError(f"Malformed catalogue: {err}") from err


def _build_catalogue(payloads: Payloads, fetched_at: datetime) -> Catalogue:
    suwar_rows = _rows_by_id(_by_language(payloads, "suwar", "suwar"))
    riwayat_rows = _rows_by_id(_by_language(payloads, "riwayat", "riwayat"))
    types_rows = _rows_by_id(_by_language(payloads, "moshaf", "riwayat"))
    reciter_rows = _rows_by_id(_by_language(payloads, "reciters", "reciters"))

    def any_row(
        rows: Mapping[Language, Mapping[int, Mapping[str, Any]]], item_id: int
    ) -> Mapping[str, Any]:
        for lang in LANGUAGES:
            if (row := rows.get(lang, {}).get(item_id)) is not None:
                return row
        raise KeyError(item_id)

    def all_ids(rows: Mapping[Language, Mapping[int, Any]]) -> list[int]:
        return sorted({item_id for lang_rows in rows.values() for item_id in lang_rows})

    suwar: dict[int, Surah] = {}
    for sid in all_ids(suwar_rows):
        row = any_row(suwar_rows, sid)
        name_ar, name_en = _names(suwar_rows, sid)
        suwar[sid] = Surah(
            number=sid,
            name_ar=name_ar,
            name_en=name_en,
            makki=bool(_int(row.get("makkia", 0))),
            start_page=_int(row.get("start_page", 0)),
            end_page=_int(row.get("end_page", 0)),
        )

    riwayat: dict[int, Riwaya] = {}
    for rid in all_ids(riwayat_rows):
        name_ar, name_en = _names(riwayat_rows, rid)
        riwayat[rid] = Riwaya(id=rid, name_ar=name_ar, name_en=name_en)

    moshaf_types: dict[int, MoshafType] = {}
    for tid in all_ids(types_rows):
        row = any_row(types_rows, tid)
        name_ar, name_en = _names(types_rows, tid)
        moshaf_types[tid] = MoshafType(
            id=tid,
            riwaya_id=_int(row["moshaf_type"]),
            style_id=_int(row["moshaf_id"]),
            name_ar=name_ar,
            name_en=name_en,
        )

    reciters: dict[int, Reciter] = {}
    for rid in all_ids(reciter_rows):
        name_ar, name_en = _names(reciter_rows, rid)
        moshaf_rows: dict[Language, dict[int, Mapping[str, Any]]] = {}
        for lang in LANGUAGES:
            reciter_row = reciter_rows.get(lang, {}).get(rid)
            if reciter_row is None:
                continue
            moshaf_rows[lang] = {
                _int(m["id"]): m for m in reciter_row.get("moshaf", [])
            }
        moshafs: list[Moshaf] = []
        for mid in all_ids(moshaf_rows):
            mrow = any_row(moshaf_rows, mid)
            m_ar, m_en = _names(moshaf_rows, mid)
            surah_list = str(mrow.get("surah_list", "")).strip()
            surahs = frozenset(_int(n) for n in surah_list.split(",") if n.strip())
            moshafs.append(
                Moshaf(
                    id=mid,
                    reciter_id=rid,
                    name_ar=m_ar,
                    name_en=m_en,
                    riwaya_id=_int(mrow["rewaya_id"]),
                    type_id=_int(mrow["moshaf_type"]),
                    server=str(mrow["server"]).strip(),
                    surahs=surahs,
                )
            )
        reciters[rid] = Reciter(
            id=rid, name_ar=name_ar, name_en=name_en, moshafs=tuple(moshafs)
        )

    _LOGGER.debug(
        "Built catalogue: %d reciters, %d moshafs, %d suwar",
        len(reciters),
        sum(len(r.moshafs) for r in reciters.values()),
        len(suwar),
    )
    return Catalogue(
        fetched_at=fetched_at,
        reciters=reciters,
        suwar=suwar,
        riwayat=riwayat,
        moshaf_types=moshaf_types,
    )
