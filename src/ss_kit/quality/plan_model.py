"""Parsers for the capability registry, the forward implementation plan, and task records."""

import re
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_HEADING = "## Capability Registry"
AGENT_SECTION = "Agent Implementation Tasks"
HUMAN_SECTION = "Human-Assisted Tasks"
PLAN_SECTIONS = (AGENT_SECTION, HUMAN_SECTION)

_ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")
_CAPABILITY = re.compile(r"^`(?P<id>[a-z0-9-]+)`$")
_SECTION = re.compile(r"^## (?P<title>.+?)\s*$")
_GROUP = re.compile(r"^### .+ -- `(?P<id>[a-z0-9-]+)`\s*$")
_TASK = re.compile(r"^#### (?P<id>[a-z0-9][a-z0-9-]*)(?P<optional> \(optional\))?\s*$")
_FIELD = re.compile(r"^- (?P<key>[A-Za-z][A-Za-z -]+):\s*(?P<value>.*)$")
_CONTINUATION = re.compile(r"^ {2,}\S")
_SERVES = re.compile(r"^`(?P<id>[a-z0-9-]+)`(?:\s|$)")
# A task-like reference: a backticked kebab-case slug with at least one hyphen.
_TASK_REFERENCE = re.compile(r"`(?P<id>[a-z0-9]+(?:-[a-z0-9]+)+)`")
_NON_BLOCKING = re.compile(r"\b(?:optional|cross-lane note|blocks):", re.IGNORECASE)
_RECORD = re.compile(r"^\d{4}-(?P<rest>[a-z0-9-]+)\.md$")


def _references(value: str) -> list[str]:
    return list(dict.fromkeys(match.group("id") for match in _TASK_REFERENCE.finditer(value)))


@dataclass(frozen=True, slots=True)
class Capability:
    """One product capability and its delivery contract."""

    identifier: str
    status: str
    evaluation: str
    implementation: str


@dataclass(slots=True)
class Task:
    """One forward task and the metadata used to schedule it."""

    identifier: str
    section: str
    group: str
    optional: bool
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def serves(self) -> str | None:
        """Return the capability id declared by the task."""
        value = self.fields.get("serves", "")
        matched = _SERVES.match(value)
        return matched.group("id") if matched else None

    @property
    def agent_status(self) -> str | None:
        """Return the normalized execution status when present."""
        value = self.fields.get("agent status")
        return value.strip().upper() if value else None

    @property
    def dependency_references(self) -> list[str]:
        """Return every task-like slug named in the `Dependencies` field, in order."""
        return _references(self.fields.get("dependencies", ""))

    @property
    def start_dependencies(self) -> list[str]:
        """Return the task ids that must leave the plan before this task can start.

        Everything after the first `Optional:`, `Cross-lane note:`, or `Blocks:` marker is
        informational: soft inputs, other-lane acceptance gates, or work this task gates.
        """
        value = self.fields.get("dependencies", "")
        marker = _NON_BLOCKING.search(value)
        return _references(value[: marker.start()] if marker else value)


def _cells(line: str) -> list[str] | None:
    matched = _ROW.match(line.strip())
    return [cell.strip() for cell in matched.group("cells").split("|")] if matched else None


def read_registry(spec: Path) -> list[Capability]:
    """Read capability rows in their declared implementation order."""
    capabilities: list[Capability] = []
    inside_registry = False
    for line in spec.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside_registry = line.strip() == REGISTRY_HEADING
            continue
        cells = _cells(line) if inside_registry else None
        if not cells or len(cells) < 5:
            continue
        identifier = _CAPABILITY.match(cells[1])
        if identifier:
            capabilities.append(
                Capability(
                    identifier=identifier.group("id"),
                    status=cells[2],
                    evaluation=cells[3],
                    implementation=cells[4],
                )
            )
    return capabilities


class _PlanReader:
    """Line-by-line state machine over the plan document."""

    def __init__(self) -> None:
        self.tasks: list[Task] = []
        self.section = ""
        self.group = ""
        self.current: Task | None = None
        self.open_field: str | None = None

    def _heading(self, line: str) -> bool:
        section_match = _SECTION.match(line)
        if section_match:
            self.section = section_match.group("title")
            self.group = ""
            self.current = None
            return True
        group_match = _GROUP.match(line)
        if group_match:
            self.group = group_match.group("id")
            self.current = None
            return True
        task_match = _TASK.match(line)
        if task_match:
            self.current = Task(
                identifier=task_match.group("id"),
                section=self.section,
                group=self.group,
                optional=bool(task_match.group("optional")),
            )
            self.tasks.append(self.current)
            return True
        return False

    def feed(self, line: str) -> None:
        if self._heading(line):
            self.open_field = None
            return
        if self.current is None:
            return
        field_match = _FIELD.match(line)
        if field_match:
            key = field_match.group("key").strip().lower()
            if key in self.current.fields:
                self.open_field = None
                return
            self.current.fields[key] = field_match.group("value").strip()
            self.open_field = key
            return
        if self.open_field and _CONTINUATION.match(line):
            joined = f"{self.current.fields[self.open_field]} {line.strip()}"
            self.current.fields[self.open_field] = joined.strip()
            return
        self.open_field = None


def read_tasks(plan: Path) -> list[Task]:
    """Read tasks in document order with their lane, group, and metadata.

    Field values include their indented continuation lines, joined by single spaces.
    """
    reader = _PlanReader()
    fenced = False
    for line in plan.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            reader.open_field = None
            continue
        if not fenced:
            reader.feed(line)
    return reader.tasks


def read_recorded_task_ids(records_dir: Path, groups: set[str]) -> set[str]:
    """Return task ids that have a record `NNNN-<group>-<task-id>.md` for a known group."""
    if not records_dir.is_dir():
        return set()
    recorded: set[str] = set()
    for record in records_dir.iterdir():
        matched = _RECORD.match(record.name)
        if not matched:
            continue
        rest = matched.group("rest")
        for group in groups:
            prefix = f"{group}-"
            if rest.startswith(prefix) and len(rest) > len(prefix):
                recorded.add(rest[len(prefix) :])
    return recorded
