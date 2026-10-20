"""Naming rules: normalisation, album names, titles, filesystem-safe paths.

Every string coming from the API passes through :func:`normalize`. Album names are
derived from the riwaya and style ids (see ``docs/api-notes.md``), never by parsing
display names, which are only a fallback for ids this table does not know.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
import re
import unicodedata

from .models import (
    SURAH_COUNT,
    Catalogue,
    Language,
    Moshaf,
    NamingOptions,
    NumberSeparator,
    Reciter,
    Surah,
    TitleFormat,
    TrackSpec,
    TrackTags,
    track_key,
)

ALBUM_SEPARATOR = " – "  # U+2013 en dash
TITLE_SEPARATOR = " – "
NAMING_FINGERPRINT_VERSION = 1
# Text between the surah number and the name: ``018 الكهف``, ``018- الكهف``, ``018 - الكهف``.
NUMBER_SEPARATOR_TEXT: dict[NumberSeparator, str] = {
    "space": " ",
    "hyphen": "- ",
    "spaced_hyphen": " - ",
}

_SOFT_HYPHEN = "­"
_WHITESPACE_RE = re.compile(r"\s+")
_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_RIWAYA_PREFIX_RE = re.compile(r"^rewayat\s+", re.IGNORECASE)

# (english, arabic) short names keyed by /riwayat id.
RIWAYA_SHORT: dict[int, tuple[str, str]] = {
    1: ("Hafs", "حفص"),
    2: ("Warsh", "ورش"),
    3: ("Khalaf", "خلف"),
    4: ("Al-Bazzi", "البزي"),
    5: ("Qalun", "قالون"),
    6: ("Qunbul", "قنبل"),
    7: ("As-Susi", "السوسي"),
    8: ("Qalun (Abu Nashit)", "قالون (أبي نشيط)"),
    9: ("Ruways & Rawh", "رويس وروح"),
    10: ("Warsh (Al-Asbahani)", "ورش (الأصبهاني)"),
    11: ("Al-Bazzi & Qunbul", "البزي وقنبل"),
    12: ("Ad-Duri (Al-Kisa'i)", "الدوري (الكسائي)"),
    13: ("Ad-Duri (Abu Amr)", "الدوري (أبي عمرو)"),
    15: ("Shu'bah", "شعبة"),
    16: ("Ibn Dhakwan", "ابن ذكوان"),
    18: ("Warsh (Al-Azraq)", "ورش (الأزرق)"),
    19: ("Hisham", "هشام"),
    20: ("Ibn Jammaz", "ابن جماز"),
}

# (english, arabic) short names keyed by style id (the ``moshaf_id`` of /moshaf).
STYLE_SHORT: dict[int, tuple[str, str]] = {
    1: ("Murattal", "مرتل"),
    2: ("Mujawwad", "مجود"),
    3: ("Mu'allim", "معلم"),
    4: ("Featured", "تلاوة مميزة"),
    20: ("1967 recording", "تسجيل 1967"),
}

# /riwayat ids that are really styles (the riwaya is unknown): id -> style id.
STYLE_ONLY_RIWAYAT: dict[int, int] = {21: 3, 22: 2}


def normalize(text: str) -> str:
    """Clean an API string: NFC, soft hyphen to hyphen, collapsed whitespace."""
    text = unicodedata.normalize("NFC", text).replace(_SOFT_HYPHEN, "-")
    text = "".join(ch if ch.isprintable() or ch.isspace() else " " for ch in text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def safe_component(text: str, *, max_len: int = 120) -> str:
    """Make one path component safe for Windows, Linux, macOS and SMB shares."""
    text = _UNSAFE_RE.sub("_", normalize(text)).strip(". ").strip()
    if not text:
        return "_"
    if text.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        text = f"_{text}"
    if len(text) > max_len:
        text = text[:max_len].rstrip(". ") or "_"
    return text


def _lang_index(language: Language) -> int:
    return 0 if language == "eng" else 1


def _riwaya_and_style(moshaf: Moshaf, catalogue: Catalogue) -> tuple[int, int | None]:
    if (mtype := catalogue.moshaf_types.get(moshaf.type_id)) is not None:
        return mtype.riwaya_id, mtype.style_id
    return moshaf.riwaya_id, None


def _fallback_riwaya(
    riwaya_id: int, moshaf: Moshaf, catalogue: Catalogue, language: Language
) -> str:
    if (riwaya := catalogue.riwayat.get(riwaya_id)) is not None:
        return _RIWAYA_PREFIX_RE.sub("", normalize(riwaya.name(language)))
    head, _, _ = normalize(moshaf.name(language)).partition(" - ")
    return _RIWAYA_PREFIX_RE.sub("", head)


def _fallback_style(moshaf: Moshaf, catalogue: Catalogue, language: Language) -> str:
    source = catalogue.moshaf_types.get(moshaf.type_id)
    name = normalize(source.name(language) if source else moshaf.name(language))
    _, sep, tail = name.partition(" - ")
    return tail if sep and tail else STYLE_SHORT[1][_lang_index(language)]


def album_name(moshaf: Moshaf, catalogue: Catalogue, language: Language) -> str:
    """Return the short album name of a version, e.g. ``Hafs – Murattal``."""
    idx = _lang_index(language)
    riwaya_id, style_id = _riwaya_and_style(moshaf, catalogue)
    if riwaya_id in STYLE_ONLY_RIWAYAT:
        only_style = STYLE_SHORT.get(
            STYLE_ONLY_RIWAYAT[riwaya_id] if style_id is None else style_id
        )
        if only_style is not None:
            return only_style[idx]
        return _fallback_style(moshaf, catalogue, language)
    riwaya_short = RIWAYA_SHORT.get(riwaya_id)
    riwaya = (
        riwaya_short[idx]
        if riwaya_short
        else _fallback_riwaya(riwaya_id, moshaf, catalogue, language)
    )
    style_short = STYLE_SHORT.get(style_id) if style_id is not None else None
    style = (
        style_short[idx]
        if style_short
        else _fallback_style(moshaf, catalogue, language)
    )
    return f"{riwaya}{ALBUM_SEPARATOR}{style}"


def album_names_for_reciter(
    moshafs: Sequence[Moshaf], catalogue: Catalogue, language: Language
) -> dict[int, str]:
    """Return album names for a reciter's versions, disambiguating duplicates.

    Two versions that would collapse to the same name get `` (#<moshaf id>)``
    appended, deterministically.
    """
    names = {m.id: album_name(m, catalogue, language) for m in moshafs}
    counts: dict[str, int] = {}
    for name in names.values():
        counts[name] = counts.get(name, 0) + 1
    return {
        moshaf_id: f"{name} (#{moshaf_id})" if counts[name] > 1 else name
        for moshaf_id, name in names.items()
    }


def track_number(surah: int) -> str:
    """Return the zero-padded surah number used in titles and file names."""
    return f"{surah:03d}"


def surah_display(surah: Surah, title_format: TitleFormat) -> str:
    """Return the name part of a title for the chosen format."""
    if title_format == "number_ar":
        return surah.name_ar
    if title_format == "number_en":
        return surah.name_en
    return f"{surah.name_ar}{TITLE_SEPARATOR}{surah.name_en}"


def track_title(
    surah: Surah, title_format: TitleFormat, separator: NumberSeparator = "space"
) -> str:
    """Return the ``TIT2`` title, e.g. ``018 الكهف`` or ``018- الكهف``."""
    sep = NUMBER_SEPARATOR_TEXT[separator]
    return f"{track_number(surah.number)}{sep}{surah_display(surah, title_format)}"


def sort_title(surah: Surah, separator: NumberSeparator = "space") -> str:
    """Return the ``TSOT`` sort title, always English."""
    return (
        f"{track_number(surah.number)}{NUMBER_SEPARATOR_TEXT[separator]}{surah.name_en}"
    )


def track_filename(
    surah: Surah, title_format: TitleFormat, separator: NumberSeparator = "space"
) -> str:
    """Return the file name, e.g. ``018 الكهف.mp3``."""
    name = safe_component(surah_display(surah, title_format))
    return f"{track_number(surah.number)}{NUMBER_SEPARATOR_TEXT[separator]}{name}.mp3"


def naming_fingerprint(options: NamingOptions) -> str:
    """Return a string that changes whenever tags or paths would change.

    The default separator is left out so indexes written by 0.1.0 stay valid.
    """
    fingerprint = (
        f"{NAMING_FINGERPRINT_VERSION}:{options.names_language}:{options.title_format}"
    )
    if options.number_separator != "space":
        fingerprint += f":{options.number_separator}"
    return fingerprint


def build_track(
    reciter: Reciter,
    moshaf: Moshaf,
    surah: Surah,
    options: NamingOptions,
    *,
    album: str,
    album_sort: str,
) -> TrackSpec:
    """Build path and tags together so they can never disagree."""
    artist = normalize(reciter.name(options.names_language))
    tags = TrackTags(
        artist=artist,
        album_artist=artist,
        album=album,
        title=track_title(surah, options.title_format, options.number_separator),
        track=(surah.number, SURAH_COUNT),
        sort_artist=normalize(reciter.name_en),
        sort_album_artist=normalize(reciter.name_en),
        sort_album=album_sort,
        sort_title=sort_title(surah, options.number_separator),
        reciter_id=reciter.id,
        moshaf_id=moshaf.id,
        surah=surah.number,
    )
    relative = PurePosixPath(
        safe_component(artist),
        safe_component(album),
        track_filename(surah, options.title_format, options.number_separator),
    )
    return TrackSpec(
        key=track_key(reciter.id, moshaf.id, surah.number),
        url=moshaf.file_url(surah.number),
        relative_path=relative.as_posix(),
        tags=tags,
        surah=surah.number,
        naming_fingerprint=naming_fingerprint(options),
    )
