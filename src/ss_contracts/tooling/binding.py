"""The `ssBinding` custom property: how a message or field relates to time, space, and transport.

On `schema[0]` (message level) it may carry `timeBase`, `frame`, `modality`, and `mqttTopic`; on
a property (field level) it may carry `timeBase`, `frame`, `unit`, and `modality`. Values:

- `timeBase`: `utc` (wall clock), `gps`, `tai`, `monotonic` (host uptime), or `media` (offset
  into a video or audio timeline);
- `frame`: `wgs84` (lat, lon, alt), `enu` (local east-north-up meters around a site origin), or
  `image` (pixel coordinates);
- `unit`: a UCUM-style unit code such as `m`, `dB`, `Cel`, or `%`, only on numeric fields;
- `modality`: a lowercase sensor modality such as `acoustic`, `camera`, or `lorawan`;
- `mqttTopic`: the `ss/...` topic pattern the message is published on; `+` and `{name}`
  placeholders match one level, `#` matches the rest and may only come last.
"""

import re
from collections.abc import Mapping
from typing import Any

BINDING_PROPERTY = "ssBinding"

TIME_BASES: frozenset[str] = frozenset({"utc", "gps", "tai", "monotonic", "media"})
FRAMES: frozenset[str] = frozenset({"wgs84", "enu", "image"})

MESSAGE_KEYS: tuple[str, ...] = ("timeBase", "frame", "modality", "mqttTopic")
FIELD_KEYS: tuple[str, ...] = ("timeBase", "frame", "unit", "modality")

_MODALITY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_UNIT_RE = re.compile(r"^[A-Za-z0-9%/.*^\[\]{}'-]+$")
_TOPIC_LEVEL_RE = re.compile(r"^([A-Za-z0-9_.-]+|\+|\{[a-z][a-z0-9_]*\})$")


def topic_errors(topic: str) -> list[str]:
    if not topic.startswith("ss/"):
        return [f"mqttTopic '{topic}' must start with 'ss/'"]
    levels = topic.split("/")
    errors: list[str] = []
    for index, level in enumerate(levels):
        if level == "#" and index == len(levels) - 1:
            continue
        if not _TOPIC_LEVEL_RE.match(level):
            errors.append(f"mqttTopic '{topic}' has an invalid level '{level}'")
    return errors


def _value_errors(key: str, value: str) -> list[str]:
    if key == "timeBase" and value not in TIME_BASES:
        return [f"timeBase '{value}' is not one of {sorted(TIME_BASES)}"]
    if key == "frame" and value not in FRAMES:
        return [f"frame '{value}' is not one of {sorted(FRAMES)}"]
    if key == "modality" and not _MODALITY_RE.match(value):
        return [f"modality '{value}' must match {_MODALITY_RE.pattern}"]
    if key == "unit" and not _UNIT_RE.match(value):
        return [f"unit '{value}' is not a UCUM-style unit code"]
    if key == "mqttTopic":
        return topic_errors(value)
    return []


def binding_errors(value: Any, allowed_keys: tuple[str, ...]) -> list[str]:
    """Validate one ssBinding value; an absent binding (None) is valid."""
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [f"{BINDING_PROPERTY} must be a mapping"]
    errors: list[str] = []
    for key, item in value.items():
        if key not in allowed_keys:
            errors.append(
                f"{BINDING_PROPERTY} key '{key}' is not allowed here {list(allowed_keys)}"
            )
        elif not isinstance(item, str) or not item:
            errors.append(f"{BINDING_PROPERTY}.{key} must be a non-empty string")
        else:
            errors.extend(_value_errors(key, item))
    return errors


def normalize_binding(value: Any) -> dict[str, str]:
    """Return a validated binding as a key-sorted plain dict (empty when absent)."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(value[key]) for key in sorted(value)}
