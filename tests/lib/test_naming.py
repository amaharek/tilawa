"""Tests for naming rules against real catalogue names."""

from dataclasses import replace

from custom_components.tilawa.lib import naming
from custom_components.tilawa.lib.library import desired_tracks
from custom_components.tilawa.lib.models import (
    Catalogue,
    Moshaf,
    NamingOptions,
    Selection,
)

EXPECTED_ALBUMS_EN = {
    11: "Hafs – Murattal",
    12: "Hafs – Mujawwad",
    13: "Hafs – Mu'allim",
    14: "Hafs – Featured",
    120: "Hafs – 1967 recording",
    21: "Warsh – Murattal",
    31: "Khalaf – Murattal",
    41: "Al-Bazzi – Murattal",
    51: "Qalun – Murattal",
    52: "Qalun – Mujawwad",
    61: "Qunbul – Murattal",
    71: "As-Susi – Murattal",
    81: "Qalun (Abu Nashit) – Murattal",
    91: "Ruways & Rawh – Murattal",
    101: "Warsh (Al-Asbahani) – Murattal",
    111: "Al-Bazzi & Qunbul – Murattal",
    121: "Ad-Duri (Al-Kisa'i) – Murattal",
    131: "Ad-Duri (Abu Amr) – Murattal",
    132: "Ad-Duri (Abu Amr) – Mujawwad",
    151: "Shu'bah – Murattal",
    152: "Shu'bah – Mujawwad",
    161: "Ibn Dhakwan – Murattal",
    181: "Warsh (Al-Azraq) – Murattal",
    191: "Hisham – Murattal",
    201: "Ibn Jammaz – Murattal",
    213: "Mu'allim",
    222: "Mujawwad",
}
EXPECTED_ALBUMS_AR = {
    11: "حفص – مرتل",
    21: "ورش – مرتل",
    14: "حفص – تلاوة مميزة",
    120: "حفص – تسجيل 1967",
    213: "معلم",
    222: "مجود",
}


def _moshaf_of_type(catalogue: Catalogue, type_id: int) -> Moshaf:
    base = catalogue.moshafs[118]
    mtype = catalogue.moshaf_types[type_id]
    return replace(base, type_id=type_id, riwaya_id=mtype.riwaya_id)


def test_every_moshaf_type_has_a_table_derived_english_album(
    catalogue: Catalogue,
) -> None:
    assert set(EXPECTED_ALBUMS_EN) == set(catalogue.moshaf_types)
    for type_id, expected in EXPECTED_ALBUMS_EN.items():
        moshaf = _moshaf_of_type(catalogue, type_id)
        assert naming.album_name(moshaf, catalogue, "eng") == expected, type_id


def test_arabic_albums(catalogue: Catalogue) -> None:
    for type_id, expected in EXPECTED_ALBUMS_AR.items():
        moshaf = _moshaf_of_type(catalogue, type_id)
        assert naming.album_name(moshaf, catalogue, "ar") == expected, type_id


def test_unknown_type_falls_back_to_display_names(catalogue: Catalogue) -> None:
    moshaf = replace(
        catalogue.moshafs[118],
        type_id=999,
        riwaya_id=2,
        name_en="Rewayat Warsh A'n Nafi' - Something New ",
    )
    assert naming.album_name(moshaf, catalogue, "eng") == "Warsh – Something New"
    unknown_riwaya = replace(moshaf, riwaya_id=777, name_en="Mystery - Style")
    assert naming.album_name(unknown_riwaya, catalogue, "eng") == "Mystery – Style"


def test_duplicate_albums_are_disambiguated(catalogue: Catalogue) -> None:
    first = catalogue.moshafs[118]
    second = replace(first, id=9999)
    names = naming.album_names_for_reciter([first, second], catalogue, "eng")
    assert names == {118: "Hafs – Murattal (#118)", 9999: "Hafs – Murattal (#9999)"}
    assert naming.album_names_for_reciter([first], catalogue, "eng") == {
        118: "Hafs – Murattal"
    }


def test_normalize_cleans_api_strings() -> None:
    assert naming.normalize("Ya­Sin ") == "Ya-Sin"
    assert naming.normalize("Sho'bah  A'n Asim") == "Sho'bah A'n Asim"
    assert naming.normalize("  ياسر المزروعي ") == "ياسر المزروعي"


def test_safe_component() -> None:
    assert naming.safe_component("CON") == "_CON"
    assert naming.safe_component("a/b:c*?") == "a_b_c__"
    assert naming.safe_component("name. ") == "name"
    assert naming.safe_component("   ") == "_"
    assert naming.safe_component("حفص – مرتل") == "حفص – مرتل"
    assert len(naming.safe_component("x" * 500)) == 120


def test_titles_and_filenames(catalogue: Catalogue) -> None:
    kahf = catalogue.suwar[18]
    assert naming.track_title(kahf, "number_ar") == "018 الكهف"
    assert naming.track_title(kahf, "number_en") == "018 Al-Kahf"
    assert naming.track_title(kahf, "number_both") == "018 الكهف – Al-Kahf"
    assert naming.sort_title(kahf) == "018 Al-Kahf"
    assert naming.track_filename(kahf, "number_ar") == "018 الكهف.mp3"
    assert naming.track_filename(catalogue.suwar[36], "number_en") == "036 Ya-Sin.mp3"


def test_build_track_path_and_tags(catalogue: Catalogue) -> None:
    reciter = catalogue.reciters[118]
    moshaf = catalogue.moshafs[118]
    spec = naming.build_track(
        reciter,
        moshaf,
        catalogue.suwar[18],
        NamingOptions(),
        album="حفص – مرتل",
        album_sort="Hafs – Murattal",
    )
    assert spec.key == "118:118:18"
    assert spec.url == "https://cdn.mp3quran.net/audio/mahmoud-husary/r1/018.mp3"
    assert spec.relative_path == "محمود خليل الحصري/حفص – مرتل/018 الكهف.mp3"
    assert spec.tags.artist == spec.tags.album_artist == "محمود خليل الحصري"
    assert spec.tags.sort_artist == "Mahmoud Khalil Al-Hussary"
    assert spec.tags.track == (18, 114)
    assert spec.tags.disc == (1, 1)
    assert spec.tags.genre == "Quran"
    assert spec.naming_fingerprint == "1:ar:number_ar"


def test_album_and_artist_are_identical_across_tracks(catalogue: Catalogue) -> None:
    """Music Assistant splits artists/albums if any track differs."""
    reciter = catalogue.reciters[118]
    selections = [Selection(118, m.id) for m in reciter.moshafs]
    tracks, missing = desired_tracks(catalogue, selections, NamingOptions())
    assert not missing
    assert len(tracks) == sum(len(m.surahs) for m in reciter.moshafs)
    by_moshaf: dict[int, set[tuple[str, str, str]]] = {}
    for spec in tracks.values():
        by_moshaf.setdefault(spec.tags.moshaf_id, set()).add(
            (spec.tags.album, spec.tags.artist, spec.tags.album_artist)
        )
    assert all(len(combos) == 1 for combos in by_moshaf.values())
    artists = {spec.tags.artist for spec in tracks.values()}
    assert artists == {"محمود خليل الحصري"}
    albums = {next(iter(c))[0] for c in by_moshaf.values()}
    assert len(albums) == len(reciter.moshafs)


def test_number_separator(catalogue: Catalogue) -> None:
    kahf = catalogue.suwar[18]
    assert naming.track_title(kahf, "number_ar", "hyphen") == "018- الكهف"
    assert naming.track_title(kahf, "number_en", "spaced_hyphen") == "018 - Al-Kahf"
    assert naming.track_filename(kahf, "number_ar", "hyphen") == "018- الكهف.mp3"
    assert naming.sort_title(kahf, "spaced_hyphen") == "018 - Al-Kahf"
    # The default keeps the 0.1.0 fingerprint so existing indexes stay valid.
    assert naming.naming_fingerprint(NamingOptions()) == "1:ar:number_ar"
    assert (
        naming.naming_fingerprint(NamingOptions(number_separator="hyphen"))
        == "1:ar:number_ar:hyphen"
    )
