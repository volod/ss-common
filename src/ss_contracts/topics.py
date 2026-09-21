"""Runtime MQTT topic map: build, match, and resolve `ss/...` topics (standard library only).

`contracts/topics.yaml` is the source; `ss-contracts generate` commits it as
`ss_contracts.models.topic_map` (drift-gated like the models), so an installed package resolves
topics without YAML or the contract tree. The authoring rules and checks live in
`ss_contracts.tooling.topics`.
"""

import pathlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TOPICS_FILENAME = "topics.yaml"
TOPICS_VERSION = 1
QOS_LEVELS: frozenset[int] = frozenset({0, 1, 2})
PLACEHOLDER_RE = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
LITERAL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# A concrete level must be non-empty and hold no MQTT separator or wildcard.
VALUE_RE = re.compile(r"^[^/+#\x00]+$")


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
            match.group(1) for level in self.levels if (match := PLACEHOLDER_RE.match(level))
        )

    def match(self, topic: str) -> dict[str, str] | None:
        """Placeholder values when `topic` matches this pattern, else None."""
        values = topic.split("/")
        if len(values) != len(self.levels):
            return None
        params: dict[str, str] = {}
        for level, value in zip(self.levels, values, strict=True):
            placeholder = PLACEHOLDER_RE.match(level)
            if placeholder is None:
                if level != value:
                    return None
            elif VALUE_RE.match(value):
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
            placeholder = PLACEHOLDER_RE.match(level)
            if placeholder is None:
                levels.append(level)
                continue
            value = str(params[placeholder.group(1)])
            if not VALUE_RE.match(value):
                raise ValueError(f"{self.pattern}: '{value}' is not a single topic level")
            levels.append(value)
        return "/".join(levels)

    def subscription(self) -> str:
        """The MQTT subscription filter for this pattern (`+` for every placeholder)."""
        return "/".join("+" if PLACEHOLDER_RE.match(level) else level for level in self.levels)


@dataclass(frozen=True)
class TopicMap:
    entries: tuple[TopicEntry, ...]
    path: pathlib.Path | None = None

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
    if type(qos) is not int or qos not in QOS_LEVELS:
        raise TopicMapError(f"{where}: qos must be 0, 1, or 2")
    if not isinstance(retain, bool):
        raise TopicMapError(f"{where}: retain must be true or false")
    description = item.get("description", "")
    if not isinstance(description, str):
        raise TopicMapError(f"{where}: description must be a string")
    return TopicEntry(pattern, contract, int(qos), retain, description)


def topic_map_from_document(doc: Any, path: pathlib.Path | None = None) -> TopicMap:
    """A topic map from a parsed `topics.yaml` document; `TopicMapError` when unusable."""
    where = path if path is not None else TOPICS_FILENAME
    if (
        not isinstance(doc, Mapping)
        or type(doc.get("topicsVersion")) is not int
        or doc["topicsVersion"] != TOPICS_VERSION
    ):
        raise TopicMapError(f"{where}: topicsVersion must be {TOPICS_VERSION}")
    topics = doc.get("topics")
    if not isinstance(topics, list):
        raise TopicMapError(f"{where}: 'topics' must be a list")
    return TopicMap(tuple(_entry(index, item) for index, item in enumerate(topics)), path)


def committed_topic_map() -> TopicMap:
    """The topic map committed with this package (`ss_contracts.models.topic_map`)."""
    from ss_contracts.models.topic_map import TOPICS

    return TopicMap(tuple(TopicEntry(*row) for row in TOPICS))
