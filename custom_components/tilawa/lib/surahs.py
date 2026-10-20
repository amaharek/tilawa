"""Parsing and formatting of surah range strings such as ``78-114``."""

from __future__ import annotations

from collections.abc import Iterable

from .models import SURAH_COUNT


def parse_range(text: str) -> frozenset[int]:
    """Parse ``"78-114"`` or ``"1, 36, 55-56"`` into a set of surah numbers.

    Raises ``ValueError`` with a short message on malformed or out-of-range input.
    """
    numbers: set[int] = set()
    for raw_part in text.replace("،", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        start_text, sep, end_text = part.partition("-")
        try:
            start = int(start_text)
            end = int(end_text) if sep else start
        except ValueError as err:
            raise ValueError(f"'{part}' is not a surah number or range") from err
        if not (1 <= start <= SURAH_COUNT and 1 <= end <= SURAH_COUNT):
            raise ValueError(f"'{part}' is outside 1-{SURAH_COUNT}")
        if end < start:
            raise ValueError(f"'{part}' runs backwards")
        numbers.update(range(start, end + 1))
    if not numbers:
        raise ValueError("no surahs given")
    return frozenset(numbers)


def format_range(surahs: Iterable[int]) -> str:
    """Render a set of surah numbers compactly, e.g. ``"1, 36, 55-56"``."""
    ordered = sorted(set(surahs))
    if not ordered:
        return ""
    parts: list[str] = []
    start = prev = ordered[0]
    for number in ordered[1:]:
        if number == prev + 1:
            prev = number
            continue
        parts.append(_span(start, prev))
        start = prev = number
    parts.append(_span(start, prev))
    return ", ".join(parts)


def _span(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"
