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

import json
import pathlib
from collections.abc import Collection, Mapping

import yaml

from ss_contracts.tooling.binding import topic_errors
from ss_contracts.tooling.odcs import ContractSpec
from ss_contracts.topics import (
    LITERAL_RE,
    PLACEHOLDER_RE,
    QOS_LEVELS,
    TOPICS_FILENAME,
    TOPICS_VERSION,
    TopicEntry,
    TopicMap,
    TopicMapError,
    topic_map_from_document,
)

__all__ = [
    "QOS_LEVELS",
    "TOPICS_FILENAME",
    "TOPICS_VERSION",
    "TopicEntry",
    "TopicMap",
    "TopicMapError",
    "load_topic_map",
    "patterns_overlap",
    "render_topic_map_module",
    "topic_map_errors",
    "topic_map_from_document",
]


def load_topic_map(root: pathlib.Path) -> TopicMap | None:
    """Parse `<root>/topics.yaml`; None when the file is absent."""
    path = root / TOPICS_FILENAME
    if not path.is_file():
        return None
    return topic_map_from_document(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def _pattern_errors(entry: TopicEntry) -> list[str]:
    errors = topic_errors(entry.pattern)
    if errors:
        return errors
    for level in entry.levels[1:]:
        if not (LITERAL_RE.match(level) or PLACEHOLDER_RE.match(level)):
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
        a == b or PLACEHOLDER_RE.match(a) or PLACEHOLDER_RE.match(b)
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


def render_topic_map_module(topic_map: TopicMap) -> str:
    """Python source of `ss_contracts.models.topic_map` for the runtime topic resolver."""
    rows = "".join(
        f"    ({json.dumps(entry.pattern)}, {json.dumps(entry.contract)}, {entry.qos}, "
        f"{entry.retain!r}),\n"
        for entry in topic_map.entries
    )
    return (
        f'"""Generated from contracts/{TOPICS_FILENAME}; do not edit. Regenerate with '
        f'`make contracts-gen`."""\n\n'
        f"TOPICS_VERSION = {TOPICS_VERSION}\n\n"
        "# (pattern, contract, qos, retain)\n"
        f"TOPICS: tuple[tuple[str, str, int, bool], ...] = (\n{rows})\n"
    )
