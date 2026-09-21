import os
from pathlib import Path

import pytest

from ss_kit.env import (
    env_bool,
    env_csv,
    env_float,
    env_int,
    env_json_dict,
    load_env_files,
    parse_env_text,
    read_env_file,
    set_env_if_present,
)

DIALECT = """
# comment line
export EXPORTED=yes
PLAIN = value with spaces   # trailing comment
HASH_IN_VALUE=abc#def
SINGLE='literal ${PLAIN} # kept'
DOUBLE="line1\\nline2 \\"quoted\\""
MULTI="first
second"
EMPTY=
BARE
REF=${PLAIN}/sub
DEFAULTED=${MISSING_VAR:-fallback}
EMPTY_REF=${EMPTY:-unused}
FROM_ENV=${OUTER_VAR}
"""


def test_parse_env_text_dialect() -> None:
    values = parse_env_text(DIALECT, environ={"OUTER_VAR": "outer", "PLAIN": "ignored"})

    assert values == {
        "EXPORTED": "yes",
        "PLAIN": "value with spaces",
        "HASH_IN_VALUE": "abc#def",
        "SINGLE": "literal ${PLAIN} # kept",
        "DOUBLE": 'line1\nline2 "quoted"',
        "MULTI": "first\nsecond",
        "EMPTY": "",
        "BARE": None,
        "REF": "value with spaces/sub",
        "DEFAULTED": "fallback",
        "EMPTY_REF": "",
        "FROM_ENV": "outer",
    }


def test_parse_env_text_skips_malformed_lines() -> None:
    assert parse_env_text("not a line\n9BAD=1\nGOOD=1\n", environ={}) == {"GOOD": "1"}


def test_parse_env_text_rejects_unterminated_quotes() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        parse_env_text('A="open\n', environ={})
    with pytest.raises(ValueError, match="unterminated"):
        parse_env_text("A='open\n", environ={})


def test_load_env_files_layers_without_overriding(tmp_path: Path) -> None:
    low, high = tmp_path / "low.env", tmp_path / "high.env"
    low.write_text("A=low\nB=low\nC=low\n", encoding="utf-8")
    high.write_text("B=high\nD\n", encoding="utf-8")
    environ = {"C": "process"}

    applied = load_env_files([low, tmp_path / "absent.env", high], environ=environ)

    assert environ == {"A": "low", "B": "high", "C": "process", "D": ""}
    assert applied == {"A": "low", "B": "high", "D": ""}
    assert read_env_file(tmp_path / "absent.env") == {}


def test_typed_getters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIT_BOOL", " TRUE ")
    monkeypatch.setenv("KIT_INT", "12")
    monkeypatch.setenv("KIT_BAD_INT", "x")
    monkeypatch.setenv("KIT_FLOAT", "0.5")
    monkeypatch.setenv("KIT_BAD_FLOAT", "nan-ish")
    monkeypatch.delenv("KIT_UNSET", raising=False)

    assert env_bool("KIT_BOOL", False) is True
    assert env_bool("KIT_UNSET", True) is True
    assert env_int("KIT_INT", 1) == 12
    assert env_int("KIT_BAD_INT", 3) == 3
    assert env_float("KIT_FLOAT", 1.0) == 0.5
    assert env_float("KIT_BAD_FLOAT", 2.0) == 2.0


def test_load_env_files_expands_layers_in_supplied_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OUTER", "ambient")
    low, high = tmp_path / "low.env", tmp_path / "high.env"
    low.write_text("BASE=low\nFIRST=${OUTER}\n", encoding="utf-8")
    high.write_text("SECOND=${BASE}/${OUTER}\nBASE=high\n", encoding="utf-8")
    env = {"OUTER": "supplied"}
    assert load_env_files([low, high], environ=env) == {
        "BASE": "high",
        "FIRST": "supplied",
        "SECOND": "low/supplied",
    }


def test_load_env_files_empty_mapping_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OUTER", "ambient")
    path = tmp_path / "values.env"
    path.write_text("RESULT=${OUTER:-fallback}\n", encoding="utf-8")
    assert load_env_files([path], environ={}) == {"RESULT": "fallback"}


def test_layer_expansion_preserves_environment_precedence(tmp_path: Path) -> None:
    low, high = tmp_path / "low.env", tmp_path / "high.env"
    low.write_text("BASE=low\n", encoding="utf-8")
    high.write_text("RESULT=${BASE}\n", encoding="utf-8")
    env = {"BASE": "process"}
    assert load_env_files([low, high], environ=env) == {"RESULT": "process"}
    assert env["BASE"] == "process"


def test_layer_parse_failure_does_not_partially_update_environment(tmp_path: Path) -> None:
    low, high = tmp_path / "low.env", tmp_path / "high.env"
    low.write_text("NEW=value\n", encoding="utf-8")
    high.write_text('BAD="unterminated', encoding="utf-8")
    env = {"EXISTING": "unchanged"}
    with pytest.raises(ValueError, match="unterminated"):
        load_env_files([low, high], environ=env)
    assert env == {"EXISTING": "unchanged"}


def test_env_csv_parses_trimmed_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_CSV", " alpha, beta ,gamma ")
    assert env_csv("TEST_CSV") == ["alpha", "beta", "gamma"]
    monkeypatch.setenv("TEST_CSV", " ")
    assert env_csv("TEST_CSV", [" x ", ""]) == ["x"]


def test_env_json_dict_uses_fallback_and_error_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def on_error(message: str, key: str) -> None:
        seen.append(message % key)

    monkeypatch.setenv("TEST_JSON", "{bad")
    assert env_json_dict("TEST_JSON", default={"f": "y"}, on_error=on_error) == {"f": "y"}
    monkeypatch.setenv("TEST_JSON", "[1]")
    assert env_json_dict("TEST_JSON", on_error=on_error) == {}
    monkeypatch.setenv("TEST_JSON", '{"a": 1}')
    assert env_json_dict("TEST_JSON") == {"a": "1"}
    assert seen == [
        "TEST_JSON contains invalid JSON; using default value",
        "TEST_JSON must be a JSON object; using default value",
    ]


def test_set_env_if_present_does_not_write_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAYBE_SET", raising=False)
    set_env_if_present("MAYBE_SET", "")
    set_env_if_present("MAYBE_SET", None)
    assert "MAYBE_SET" not in os.environ

    set_env_if_present("MAYBE_SET", Path("/srv/value"))
    assert os.environ["MAYBE_SET"] == "/srv/value"
