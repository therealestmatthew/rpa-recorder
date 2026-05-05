"""Tests for `rpa_recorder.cli.params` parsers."""

import pytest
import typer

from rpa_recorder.cli.params import collect_params, parse_key_value


def test_parse_key_value_basic() -> None:
    assert parse_key_value("name=alice") == ("name", "alice")


def test_parse_key_value_value_contains_equals() -> None:
    assert parse_key_value("x=a=b") == ("x", "a=b")


def test_parse_key_value_empty_value_allowed() -> None:
    assert parse_key_value("k=") == ("k", "")


def test_parse_key_value_strips_whitespace_around_key() -> None:
    assert parse_key_value("  k = v") == ("k", " v")


def test_parse_key_value_missing_equals_raises() -> None:
    with pytest.raises(typer.BadParameter):
        parse_key_value("noequals")


def test_parse_key_value_empty_key_raises() -> None:
    with pytest.raises(typer.BadParameter):
        parse_key_value("=value")


def test_collect_params_aggregates() -> None:
    assert collect_params(["a=1", "b=2"]) == {"a": "1", "b": "2"}


def test_collect_params_empty_list() -> None:
    assert collect_params([]) == {}


def test_collect_params_rejects_duplicate_keys() -> None:
    with pytest.raises(typer.BadParameter):
        collect_params(["a=1", "a=2"])
