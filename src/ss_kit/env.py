"""Environment files and typed environment access, standard library only.

`parse_env_text` reads the `.env` dialect the ss services use (the python-dotenv subset):

- `KEY=value`, optional `export ` prefix, blank lines and `#` comments;
- unquoted values end at ` #` (inline comment) and are stripped;
- single-quoted values are literal; double-quoted values honor `\\n`, `\\t`, `\\"`, and `\\\\`
  escapes and may span lines;
- `${NAME}` and `${NAME:-default}` expand in unquoted and double-quoted values; a value defined
  earlier in the same file wins over `os.environ`, and a name found in neither expands to the
  default (or `""`);
- a bare `KEY` with no `=` yields None.

`load_env_files` applies files in order (later files win) without overriding variables already
present in the process environment.
"""

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

_KEY_RE = re.compile(r"(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*")
_EXPAND_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    '"': '"',
    "'": "'",
    "\\": "\\",
}

EnvValues = dict[str, str | None]


def _expand(value: str, defined: Mapping[str, str | None], environ: Mapping[str, str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        found = defined[name] if name in defined else environ.get(name)
        if found is None:
            return default if default is not None else ""
        return found

    return _EXPAND_RE.sub(_sub, value)


def _double_quoted(text: str, start: int) -> tuple[str, int]:
    """Value of the double-quoted string opening at `text[start]`, and the index after it."""
    out: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            index += 2
            continue
        if char == '"':
            return "".join(out), index + 1
        out.append(char)
        index += 1
    raise ValueError("unterminated double-quoted value")


def _rest_of_line(text: str, index: int) -> int:
    end = text.find("\n", index)
    return len(text) if end < 0 else end + 1


def _unquoted(text: str, index: int) -> tuple[str, int]:
    end = _rest_of_line(text, index)
    raw = text[index:end].rstrip("\r\n")
    comment = re.search(r"\s#", raw)
    if comment:
        raw = raw[: comment.start()]
    return raw.strip(), end


def _value(text: str, index: int) -> tuple[str, bool, int]:
    """Parse the value starting at `index`: (value, expandable, index after the line)."""
    while index < len(text) and text[index] in " \t":
        index += 1
    if index < len(text) and text[index] == "'":
        close = text.find("'", index + 1)
        if close < 0:
            raise ValueError("unterminated single-quoted value")
        return text[index + 1 : close], False, _rest_of_line(text, close + 1)
    if index < len(text) and text[index] == '"':
        value, after = _double_quoted(text, index)
        return value, True, _rest_of_line(text, after)
    value, after = _unquoted(text, index)
    return value, True, after


def parse_env_text(text: str, *, environ: Mapping[str, str] | None = None) -> EnvValues:
    """Parse `.env` text into ordered values (see the module docstring for the dialect)."""
    env = os.environ if environ is None else environ
    values: EnvValues = {}
    index = 0
    while index < len(text):
        line_end = _rest_of_line(text, index)
        line = text[index:line_end]
        stripped = line.strip()
        match = _KEY_RE.match(text, index + len(line) - len(line.lstrip()))
        if not stripped or stripped.startswith("#") or match is None:
            index = line_end
            continue
        key, after_key = match.group(1), match.end()
        if text.startswith("=", after_key):
            value, expandable, index = _value(text, after_key + 1)
            values[key] = _expand(value, values, env) if expandable else value
            continue
        if not text[after_key:line_end].strip():
            values[key] = None
        index = line_end
    return values


def read_env_file(path: str | os.PathLike[str]) -> EnvValues:
    """Values of one `.env` file; an absent file yields no values."""
    candidate = Path(path)
    if not candidate.is_file():
        return {}
    return parse_env_text(candidate.read_text(encoding="utf-8"))


def load_env_files(
    paths: Iterable[str | os.PathLike[str]],
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Apply `.env` files in order (later wins) without overriding existing variables.

    Returns the variables this call set. A key declared without a value is set to `""`.
    """
    env = os.environ if environ is None else environ
    merged: EnvValues = {}
    for path in paths:
        merged.update(read_env_file(path))
    applied: dict[str, str] = {}
    for key, value in merged.items():
        if key not in env:
            env[key] = applied[key] = value if value is not None else ""
    return applied


def env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def env_bool(key: str, default: bool) -> bool:
    """True only for `true` (any case); other set values are False."""
    return os.getenv(key, "true" if default else "false").strip().lower() == "true"


def env_int(key: str, default: int) -> int:
    raw = os.getenv(key, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(key: str, default: float) -> float:
    raw = os.getenv(key, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


def env_csv(key: str, default: Iterable[str] = ()) -> list[str]:
    raw = os.getenv(key, "")
    if not raw.strip():
        return [str(item).strip() for item in default if str(item).strip()]
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_json_dict(
    key: str,
    *,
    default: dict[str, str] | None = None,
    on_error: Callable[[str, str], object] | None = None,
) -> dict[str, str]:
    """A JSON object from `key` with string values; `default` when unset or invalid.

    `on_error(message, key)` receives a %-style message when the value is invalid.
    """
    fallback = dict(default or {})
    raw = os.getenv(key, "")
    if not raw:
        return fallback
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        if on_error is not None:
            on_error("%s contains invalid JSON; using default value", key)
        return fallback
    if not isinstance(parsed, dict):
        if on_error is not None:
            on_error("%s must be a JSON object; using default value", key)
        return fallback
    return {str(k): str(v) for k, v in parsed.items()}


def set_env_if_present(key: str, value: Any) -> None:
    if value not in (None, ""):
        os.environ[key] = str(value)
