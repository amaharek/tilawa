"""Resumable, verified, rate-limited downloads of single audio files.

Rules learned from the live CDN (see ``docs/api-notes.md``):

* never follow a temporary redirect (302/303/307): on mp3quran's CDN that is how
  a missing surah falls back to a different reciter's file; follow a permanent one
  (301/308) only when it keeps the same ``NNN.mp3`` name (that is how the old
  ``serverN`` hosts moved to the CDN), and log it;
* resume with ``Range`` plus ``If-Range: <etag>``; a 200 answer to a ranged
  request means the file changed upstream and the partial file is discarded;
* ``Content-Length`` is exact (no chunked or compressed transfer), so the final
  size is verified against it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Protocol

import aiohttp

from .api import (
    PERMANENT_REDIRECTS,
    TEMPORARY_REDIRECTS,
    USER_AGENT,
    same_file_redirect,
)
from .models import RemoteFile

_LOGGER = logging.getLogger(__name__)

_CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")
_UNSATISFIABLE_RE = re.compile(r"bytes \*/(\d+)")
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class RunBlocking(Protocol):
    """Run a blocking callable off the event loop (``hass.async_add_executor_job``)."""

    def __call__[T](self, func: Callable[..., T], /, *args: Any) -> Awaitable[T]:
        """Schedule ``func(*args)`` and return an awaitable for its result."""
        ...


async def run_in_thread[T](func: Callable[..., T], /, *args: Any) -> T:
    """Default ``RunBlocking`` used outside Home Assistant."""
    return await asyncio.to_thread(func, *args)


class DownloadError(Exception):
    """A download failed for good."""


class RedirectRefused(DownloadError):
    """The server redirected to a different file."""


class SizeMismatch(DownloadError):
    """The downloaded size did not match ``Content-Length``."""


class DownloadCancelled(DownloadError):
    """The job was cancelled while this file was in flight."""


class _Retryable(Exception):
    """Internal: this attempt failed in a way worth retrying."""


class TokenBucket:
    """Simple shared bandwidth limiter (bytes per second)."""

    def __init__(
        self,
        rate: float,
        *,
        capacity: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Create a bucket allowing ``rate`` bytes/s with a one-second burst."""
        self._rate = rate
        self._capacity = capacity if capacity is not None else rate
        self._tokens = self._capacity
        self._monotonic = monotonic
        self._sleep = sleep
        self._last = monotonic()

    async def consume(self, amount: int) -> None:
        """Account for ``amount`` bytes, sleeping when over the budget."""
        now = self._monotonic()
        self._tokens = min(
            self._capacity, self._tokens + (now - self._last) * self._rate
        )
        self._last = now
        self._tokens -= amount
        if self._tokens < 0:
            await self._sleep(-self._tokens / self._rate)


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _truncate(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class _PartFile:
    """Blocking append-only writer; every method runs via ``run_blocking``."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any = None

    def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("ab")

    def write(self, chunk: bytes) -> int:
        return int(self._handle.write(chunk))

    def close(self) -> int:
        if self._handle is None:
            return _file_size(self._path)
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        self._handle = None
        return _file_size(self._path)


class Downloader:
    """Download audio files into ``.part`` files with resume and verification."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        max_parallel: int = 2,
        bandwidth_limit_kbps: int = 0,
        max_retries: int = 5,
        user_agent: str = USER_AGENT,
        chunk_size: int = 256 * 1024,
        run_blocking: RunBlocking = run_in_thread,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        backoff_base: float = 1.0,
    ) -> None:
        """Create a downloader bound to a session."""
        self._session = session
        self.max_parallel = max(1, max_parallel)
        self._semaphore = asyncio.Semaphore(self.max_parallel)
        self._bucket = (
            TokenBucket(bandwidth_limit_kbps * 1024.0, sleep=sleep)
            if bandwidth_limit_kbps > 0
            else None
        )
        self._max_retries = max_retries
        self._headers = {"User-Agent": user_agent}
        self._chunk_size = chunk_size
        self._run_blocking = run_blocking
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=90)

    async def async_download(
        self,
        url: str,
        part_path: Path,
        *,
        expected: RemoteFile | None = None,
        on_progress: Callable[[int], None] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> RemoteFile:
        """Download ``url`` into ``part_path`` (resuming it), verify, and describe it."""
        async with self._semaphore:
            attempt = 0
            while True:
                try:
                    return await self._attempt(
                        url, part_path, expected, on_progress, cancel
                    )
                except _Retryable as err:
                    if attempt >= self._max_retries:
                        raise DownloadError(
                            f"{url}: giving up after {attempt + 1} attempts: {err}"
                        ) from err
                    delay = self._backoff_base * (2**attempt) + random.uniform(0, 0.5)
                    _LOGGER.debug("%s: %s; retrying in %.1fs", url, err, delay)
                    await self._sleep(delay)
                    attempt += 1

    async def _attempt(
        self,
        url: str,
        part_path: Path,
        expected: RemoteFile | None,
        on_progress: Callable[[int], None] | None,
        cancel: asyncio.Event | None,
    ) -> RemoteFile:
        have = await self._run_blocking(_file_size, part_path)
        headers = dict(self._headers)
        if have > 0:
            headers["Range"] = f"bytes={have}-"
            if expected and expected.etag:
                headers["If-Range"] = expected.etag

        target = url
        for _ in range(2):
            try:
                async with self._session.get(
                    target,
                    headers=headers,
                    allow_redirects=False,
                    timeout=self._timeout,
                ) as response:
                    status = response.status
                    if status in PERMANENT_REDIRECTS:
                        redirected = same_file_redirect(
                            target, response.headers.get("Location")
                        )
                        if redirected is None:
                            raise RedirectRefused(
                                f"{target}: permanent redirect to a different file"
                            )
                        _LOGGER.info("%s moved permanently to %s", target, redirected)
                        target = redirected
                        continue
                    if status in TEMPORARY_REDIRECTS:
                        raise RedirectRefused(
                            f"{target}: temporary redirect to {response.headers.get('Location')}"
                        )
                    if status in RETRYABLE_STATUSES:
                        raise _Retryable(f"HTTP {status}")
                    if status == 416:
                        return await self._handle_unsatisfiable(
                            response, part_path, have, expected
                        )
                    if status not in (200, 206):
                        raise DownloadError(f"{target}: HTTP {status}")
                    return await self._stream(
                        response, part_path, have, on_progress, cancel
                    )
            except (aiohttp.ClientError, TimeoutError) as err:
                raise _Retryable(str(err)) from err
        raise RedirectRefused(f"{url}: too many redirects")

    async def _handle_unsatisfiable(
        self,
        response: aiohttp.ClientResponse,
        part_path: Path,
        have: int,
        expected: RemoteFile | None,
    ) -> RemoteFile:
        match = _UNSATISFIABLE_RE.match(response.headers.get("Content-Range", ""))
        total = int(match.group(1)) if match else None
        if total is not None and total == have:
            # The partial file is already complete.
            return RemoteFile(
                size=have,
                etag=response.headers.get("ETag")
                or (expected.etag if expected else None),
                last_modified=response.headers.get("Last-Modified"),
            )
        await self._run_blocking(_truncate, part_path)
        raise _Retryable("range not satisfiable; restarting from scratch")

    async def _stream(
        self,
        response: aiohttp.ClientResponse,
        part_path: Path,
        have: int,
        on_progress: Callable[[int], None] | None,
        cancel: asyncio.Event | None,
    ) -> RemoteFile:
        total: int | None
        if response.status == 206:
            match = _CONTENT_RANGE_RE.match(response.headers.get("Content-Range", ""))
            if match is None or int(match.group(1)) != have:
                await self._run_blocking(_truncate, part_path)
                raise _Retryable("unexpected Content-Range; restarting from scratch")
            total = int(match.group(3)) if match.group(3) != "*" else None
        else:
            if have > 0:
                _LOGGER.debug(
                    "%s: server ignored Range or file changed; restarting", response.url
                )
                await self._run_blocking(_truncate, part_path)
                have = 0
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None

        part = _PartFile(part_path)
        await self._run_blocking(part.open)
        written = 0
        try:
            async for chunk in response.content.iter_chunked(self._chunk_size):
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled(str(response.url))
                await self._run_blocking(part.write, chunk)
                written += len(chunk)
                if self._bucket is not None:
                    await self._bucket.consume(len(chunk))
                if on_progress is not None:
                    on_progress(len(chunk))
        finally:
            size = await self._run_blocking(part.close)

        if total is not None and size != total:
            if size > total:
                await self._run_blocking(_truncate, part_path)
            raise _Retryable(f"got {size} of {total} bytes")
        return RemoteFile(
            size=size,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
