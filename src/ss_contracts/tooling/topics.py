"""The MQTT topic map: `contracts/topics.yaml` binds each `ss/...` topic pattern to one contract.

```yaml
topicsVersion: 1
topics:
  - pattern: ss/v1/site/{site_id}/sensor/{dev_eui}/reading
    contract: sensor-reading     # a registered contract id
    qos: 1                       # 0, 1, or 2
    retain: false                # the broker keeps the last message for new subscribers
    description: One decoded LoRaWAN uplink.
```

A pattern level is a literal (`[A-Za-z0-9_.-]+`) or a named placeholder (`{name}`) that stands
for exactly one level; the anonymous `+` and `#` wildcards are not allowed, so every pattern can
also build a concrete topic. An entry without a string `pattern` and `contract`, a `qos` of 0,
1, or 2, and a boolean `retain` makes the map unusable. The map is valid when every pattern is
well formed with unique placeholder names, appears once, and names a registered contract; no two
patterns can match the same concrete topic, so a topic resolves to exactly one contract; and a
contract whose `ssBinding.mqttTopic` is set is mapped exactly once, under that pattern.
"""

import pathlib
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

import yaml

from ss_contracts.tooling.binding import topic_errors
from ss_contracts.tooling.odcs import ContractSpec

TOPICS_FILENAME = "topics.yaml"
TOPICS_VERSION = 1
QOS_LEVELS: frozenset[int] = frozenset({0, 1, 2})

_PLACEHOLDER_RE = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
_LITERAL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# A concrete level must be non-empty and hold no MQTT separator or wildcard.
_VALUE_RE = re.compile(r"^[^/+#\x00]+$")


class TopicMapError(ValueError):
    """The topic map document itself is unusable."""


@dataclass(frozen=True)
class TopicEntry:
    pattern: str
    contract: str
    qos: int
    retain: bool
    description: str = ""

    @property
    def levels(self) -> tuple[str, ...]:
        return tuple(self.pattern.split("/"))

    @property
    def placeholders(self) -> tuple[str, ...]:
        return tuple(
            match.group(1) for level in self.levels if (match := _PLACEHOLDER_RE.match(level))
        )

    def match(self, topic: str) -> dict[str, str] | None:
        """Placeholder values when `topic` matches this pattern, else None."""
        values = topic.split("/")
        if len(values) != len(self.levels):
            return None
        params: dict[str, str] = {}
        for level, value in zip(self.levels, values, strict=True):
            placeholder = _PLACEHOLDER_RE.match(level)
            if placeholder is None:
                if level != value:
                    return None
            elif _VALUE_RE.match(value):
                params[placeholder.group(1)] = value
            else:
                return None
        return params

    def build(self, **params: str) -> str:
        """The concrete topic for these placeholder values."""
        missing = sorted(set(self.placeholders) - set(params))
        extra = sorted(set(params) - set(self.placeholders))
        if missing or extra:
            raise ValueError(f"{self.pattern}: missing {missing}, unexpected {extra}")
        levels: list[str] = []
        for level in self.levels:
            placeholder = _PLACEHOLDER_RE.match(level)
            if placeholder is None:
                levels.append(level)
                continue
            value = str(params[placeholder.group(1)])
            if not _VALUE_RE.match(value):
                raise ValueError(f"{self.pattern}: '{value}' is not a single topic level")
            levels.append(value)
        return "/".join(levels)


@dataclass(frozen=True)
class TopicMap:
    path: pathlib.Path
    entries: tuple[TopicEntry, ...]

    def resolve(self, topic: str) -> tuple[TopicEntry, dict[str, str]] | None:
        """The entry a concrete topic belongs to, with its placeholder values."""
        for entry in self.entries:
            params = entry.match(topic)
            if params is not None:
                return entry, params
        return None

    def for_contract(self, contract_id: str) -> tuple[TopicEntry, ...]:
        return tuple(entry for entry in self.entries if entry.contract == contract_id)


def _entry(index: int, item: Any) -> TopicEntry:
    where = f"{TOPICS_FILENAME}: topics[{index}]"
    if not isinstance(item, Mapping):
        raise TopicMapError(f"{where} must be a mapping")
    pattern, contract = item.get("pattern"), item.get("contract")
    if not isinstance(pattern, str) or not isinstance(contract, str):
        raise TopicMapError(f"{where} needs string 'pattern' and 'contract'")
    qos, retain = item.get("qos"), item.get("retain")
    if isinstance(qos, bool) or qos not in QOS_LEVELS:
        raise TopicMapError(f"{where}: qos must be 0, 1, or 2")
    if not isinstance(retain, bool):
        raise TopicMapError(f"{where}: retain must be true or false")
    description = item.get("description", "")
    if not isinstance(description, str):
        raise TopicMapError(f"{where}: description must be a string")
    return TopicEntry(pattern, contract, int(qos), retain, description)


def load_topic_map(root: pathlib.Path) -> TopicMap | None:
    """Parse `<root>/topics.yaml`; None when the file is absent."""
    path = root / TOPICS_FILENAME
    if not path.is_file():
        return None
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping) or doc.get("topicsVersion") != TOPICS_VERSION:
        raise TopicMapError(f"{path}: topicsVersion must be {TOPICS_VERSION}")
    topics = doc.get("topics")
    if not isinstance(topics, list):
        raise TopicMapError(f"{path}: 'topics' must be a list")
    return TopicMap(path, tuple(_entry(index, item) for index, item in enumerate(topics)))


def _pattern_errors(entry: TopicEntry) -> list[str]:
    errors = topic_errors(entry.pattern)
    if errors:
        return errors
    for level in entry.levels[1:]:
        if not (_LITERAL_RE.match(level) or _PLACEHOLDER_RE.match(level)):
            errors.append(f"level '{level}' must be a literal or a {{name}} placeholder")
    names = entry.placeholders
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        errors.append(f"placeholder names {duplicated} repeat")
    return errors


def _entry_errors(entry: TopicEntry, registered: Collection[str]) -> list[str]:
    errors = _pattern_errors(entry)
    if entry.contract not in registered:
        errors.append(f"contract '{entry.contract}' is not registered")
    return [f"topic {entry.pattern}: {error}" for error in errors]


def patterns_overlap(first: TopicEntry, second: TopicEntry) -> bool:
    """True when some concrete topic matches both patterns."""
    if len(first.levels) != len(second.levels):
        return False
    return all(
        a == b or _PLACEHOLDER_RE.match(a) or _PLACEHOLDER_RE.match(b)
        for a, b in zip(first.levels, second.levels, strict=True)
    )


def _overlap_errors(entries: tuple[TopicEntry, ...]) -> list[str]:
    errors: list[str] = []
    for index, first in enumerate(entries):
        for second in entries[index + 1 :]:
            if first.pattern == second.pattern:
                errors.append(f"topic {first.pattern}: listed more than once")
            elif patterns_overlap(first, second):
                errors.append(
                    f"topic {first.pattern} and {second.pattern} can match the same topic"
                )
    return errors


def _binding_errors(topic_map: TopicMap, contracts: Mapping[str, ContractSpec]) -> list[str]:
    errors: list[str] = []
    for contract_id, spec in sorted(contracts.items()):
        declared = spec.binding.get("mqttTopic")
        if declared is None:
            continue
        patterns = [entry.pattern for entry in topic_map.for_contract(contract_id)]
        if patterns != [declared]:
            errors.append(
                f"{contract_id}: ssBinding.mqttTopic {declared} must be its only topic in "
                f"{TOPICS_FILENAME}, found {patterns}"
            )
    return errors


def topic_map_errors(
    topic_map: TopicMap, registered: Collection[str], contracts: Mapping[str, ContractSpec]
) -> list[str]:
    """Findings for a loaded topic map: `registered` holds every registry id, `contracts` the
    ones that loaded cleanly (their `mqttTopic` bindings are cross-checked)."""
    errors = [error for entry in topic_map.entries for error in _entry_errors(entry, registered)]
    errors.extend(_overlap_errors(topic_map.entries))
    errors.extend(_binding_errors(topic_map, contracts))
    return errors
