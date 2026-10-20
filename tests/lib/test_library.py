"""Tests for the index and the plan builder."""

from custom_components.tilawa.lib.library import (
    LibraryIndex,
    build_plan,
    desired_tracks,
)
from custom_components.tilawa.lib.models import (
    Catalogue,
    IndexedFile,
    NamingOptions,
    RemoteFile,
    Selection,
)
from tests.conftest import FETCHED_AT

AR = NamingOptions()
EN = NamingOptions(names_language="eng", title_format="number_en")


def _indexed(
    catalogue: Catalogue, selection: Selection, options: NamingOptions
) -> LibraryIndex:
    tracks, _ = desired_tracks(catalogue, [selection], options)
    index = LibraryIndex()
    for spec in tracks.values():
        index.add(
            IndexedFile(
                key=spec.key,
                relative_path=spec.relative_path,
                size=10,
                source_etag='"old"',
                naming_fingerprint=spec.naming_fingerprint,
                downloaded_at=FETCHED_AT,
            )
        )
    return index


def test_selection_wanted() -> None:
    available = frozenset({1, 2, 3})
    assert Selection(1, 1).wanted(available) == [1, 2, 3]
    assert Selection(1, 1, frozenset({2, 3, 99})).wanted(available) == [2, 3]
    assert Selection(118, 119).key == "118:119"


def test_plan_downloads_what_is_missing(catalogue: Catalogue) -> None:
    plan = build_plan(
        catalogue, [Selection(118, 118, frozenset({1, 18}))], AR, LibraryIndex()
    )
    assert [spec.key for spec in plan.downloads] == ["118:118:1", "118:118:18"]
    assert not plan.retags
    assert not plan.orphans
    assert not plan.missing_selections
    assert plan.is_empty is False


def test_plan_is_empty_when_everything_is_indexed(catalogue: Catalogue) -> None:
    selection = Selection(118, 118, frozenset({1, 18}))
    index = _indexed(catalogue, selection, AR)
    plan = build_plan(catalogue, [selection], AR, index, existing_keys=set(index.files))
    assert plan.is_empty


def test_plan_redownloads_files_missing_on_disk(catalogue: Catalogue) -> None:
    selection = Selection(118, 118, frozenset({1}))
    index = _indexed(catalogue, selection, AR)
    plan = build_plan(catalogue, [selection], AR, index, existing_keys=set())
    assert [spec.key for spec in plan.downloads] == ["118:118:1"]


def test_plan_retags_when_naming_changed(catalogue: Catalogue) -> None:
    selection = Selection(118, 118, frozenset({1}))
    index = _indexed(catalogue, selection, AR)
    plan = build_plan(catalogue, [selection], EN, index)
    assert not plan.downloads
    assert len(plan.retags) == 1
    indexed, spec = plan.retags[0]
    assert indexed.relative_path.startswith("محمود خليل الحصري/")
    assert (
        spec.relative_path
        == "Mahmoud Khalil Al-Hussary/Hafs – Murattal/001 Al-Fatihah.mp3"
    )


def test_plan_reports_orphans_and_missing_selections(catalogue: Catalogue) -> None:
    index = _indexed(catalogue, Selection(118, 119, frozenset({1})), AR)
    plan = build_plan(
        catalogue, [Selection(118, 118, frozenset({1})), Selection(999, 1)], AR, index
    )
    assert [file.key for file in plan.orphans] == ["118:119:1"]
    assert plan.missing_selections == [Selection(999, 1)]
    assert [spec.key for spec in plan.downloads] == ["118:118:1"]


def test_plan_redownload_changed_uses_etags(catalogue: Catalogue) -> None:
    selection = Selection(118, 118, frozenset({1, 2}))
    index = _indexed(catalogue, selection, AR)
    remote = {"118:118:1": RemoteFile(5, '"new"'), "118:118:2": RemoteFile(5, '"old"')}
    plan = build_plan(
        catalogue, [selection], AR, index, redownload_changed=True, remote=remote
    )
    assert [spec.key for spec in plan.downloads] == ["118:118:1"]
    assert plan.remote == remote


def test_index_roundtrip_and_queries(catalogue: Catalogue) -> None:
    index = _indexed(catalogue, Selection(118, 118, frozenset({1, 2})), AR)
    index.add(next(iter(_indexed(catalogue, Selection(123, 123, frozenset({1})), AR))))
    assert len(index) == 3
    assert index.total_bytes == 30
    assert index.reciter_ids() == {118, 123}
    assert sorted(index.keys_for_selection("118:118")) == ["118:118:1", "118:118:2"]
    assert "118:118:1" in index
    restored = LibraryIndex.from_dict(index.to_dict())
    assert dict(restored.files) == dict(index.files)
    assert index.remove("118:118:1") is not None
    assert index.remove("118:118:1") is None
