"""Tests for surah range parsing."""

import pytest

from custom_components.tilawa.lib.surahs import format_range, parse_range


def test_parse_simple_range() -> None:
    assert parse_range("78-114") == frozenset(range(78, 115))


def test_parse_mixed_list() -> None:
    assert parse_range(" 1, 36 ,55-56 ") == frozenset({1, 36, 55, 56})


def test_parse_accepts_arabic_comma() -> None:
    assert parse_range("1،2") == frozenset({1, 2})


@pytest.mark.parametrize("text", ["0", "115", "20-10", "abc", "", "5-", "1-2-3"])
def test_parse_rejects_bad_input(text: str) -> None:
    with pytest.raises(ValueError):
        parse_range(text)


def test_format_range() -> None:
    assert format_range({1, 36, 55, 56}) == "1, 36, 55-56"
    assert format_range(range(78, 115)) == "78-114"
    assert format_range([]) == ""
    assert format_range(parse_range("3-5,1")) == "1, 3-5"
