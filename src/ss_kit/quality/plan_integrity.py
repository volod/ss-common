"""Keep the product specification and forward plan as one coherent account.

Run: `python -m ss_kit.quality.plan_integrity [--root DIR]` (or `make lint-spec-plan`).
"""

import argparse
import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from ss_kit.quality.plan_model import (
    AGENT_SECTION,
    HUMAN_SECTION,
    PLAN_SECTIONS,
    Capability,
    Task,
    read_recorded_task_ids,
    read_registry,
    read_tasks,
)
from ss_kit.quality.project_root import discover_project_root

_LOG = logging.getLogger(__name__)

SPEC_DOC = Path("docs/design/spec.md")
PLAN_DOC = Path("docs/impl/plan.md")
RECORDS_DIR = Path("docs/impl/records")
ADHOC_GROUP = "adhoc"
SHIPPED = "shipped"
PLANNED = "planned"
VALID_CAPABILITY_STATUSES = (SHIPPED, PLANNED)
AGENT_STATUSES = ("CLEAR", "RUN NEEDED")
HUMAN_STATUSES = ("BLOCKED BY HUMAN", "HUMAN-GATED")
HUMAN_STEP = "human step"
REQUIRED_FIELDS = (
    "serves",
    "agent status",
    "dependencies",
    "user-visible outcome",
    "scope boundary",
    "data and artifact paths",
    "execution path",
    "acceptance gates",
    "documentation target",
)

_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")
_HISTORY_WORD = re.compile(r"\b(done|delivered|implemented)\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TASK_HEADING = re.compile(r"^#### ")
_VALID_TASK_HEADING = re.compile(r"^#### [a-z0-9][a-z0-9-]*(?: \(optional\))?\s*$")


def _registry_findings(capabilities: list[Capability], tasks: list[Task]) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    served = {task.serves for task in tasks}
    for capability in capabilities:
        where = f"{SPEC_DOC}: `{capability.identifier}`"
        if capability.identifier in seen:
            findings.append(f"{where}: listed twice in the capability registry")
        seen.add(capability.identifier)
        if capability.status not in VALID_CAPABILITY_STATUSES:
            findings.append(
                f"{where}: status '{capability.status}' is not one of {VALID_CAPABILITY_STATUSES}"
            )
        if capability.evaluation in ("", "-", "--"):
            findings.append(f"{where}: no evaluation declares how the capability is known")
        if capability.status == SHIPPED and not _LINK.search(capability.implementation):
            findings.append(f"{where}: shipped but has no current-documentation link")
        if capability.status == PLANNED and capability.identifier not in served:
            findings.append(f"{where}: planned but no forward task serves it")
    return findings


def _task_identity_findings(task: Task, known: set[str], identifiers: set[str]) -> list[str]:
    where = f"{PLAN_DOC}: `{task.identifier}`"
    findings: list[str] = []
    if task.identifier in identifiers:
        findings.append(f"{where}: task id is duplicated")
    identifiers.add(task.identifier)
    if task.section not in PLAN_SECTIONS:
        findings.append(f"{where}: task is outside a recognized plan lane")
    if not task.group:
        findings.append(f"{where}: task has no capability group")
    if task.serves is None:
        findings.append(f"{where}: no valid `Serves` capability id")
    elif task.serves not in known:
        findings.append(f"{where}: serves unregistered capability `{task.serves}`")
    elif task.group != task.serves:
        findings.append(f"{where}: serves `{task.serves}` under `{task.group}`")
    return findings


def _task_metadata_findings(task: Task) -> list[str]:
    where = f"{PLAN_DOC}: `{task.identifier}`"
    findings = [
        f"{where}: missing non-empty `{field.title()}` field"
        for field in REQUIRED_FIELDS
        if not task.fields.get(field)
    ]
    has_human_step = bool(task.fields.get(HUMAN_STEP))
    if task.section == HUMAN_SECTION and not has_human_step:
        findings.append(f"{where}: human-lane task is missing a non-empty `Human Step` field")
    if task.section == AGENT_SECTION and HUMAN_STEP in task.fields:
        findings.append(
            f"{where}: agent-lane task declares a `Human Step`; move it to the human lane"
        )
    return findings


def _task_status_findings(task: Task) -> list[str]:
    allowed_by_section = {
        AGENT_SECTION: AGENT_STATUSES,
        HUMAN_SECTION: HUMAN_STATUSES,
    }
    allowed = allowed_by_section.get(task.section, ())
    if task.agent_status is None or task.agent_status in allowed:
        return []
    where = f"{PLAN_DOC}: `{task.identifier}`"
    return [f"{where}: status '{task.agent_status}' is invalid in '{task.section}'"]


def _dependency_findings(tasks: list[Task], recorded: set[str]) -> list[str]:
    open_ids = {task.identifier for task in tasks}
    findings: list[str] = []
    for task in tasks:
        where = f"{PLAN_DOC}: `{task.identifier}`"
        for reference in task.dependency_references:
            if reference == task.identifier:
                findings.append(f"{where}: depends on itself")
            elif reference not in open_ids and reference not in recorded:
                findings.append(
                    f"{where}: depends on `{reference}`, which is neither an open task "
                    f"nor a finished task with a record under {RECORDS_DIR}"
                )
    return findings + _cycle_findings(tasks)


def _cycle_findings(tasks: list[Task]) -> list[str]:
    """Report start-dependency cycles, which would leave every member unschedulable."""
    graph = {task.identifier: task.start_dependencies for task in tasks}
    state: dict[str, int] = {}  # 1 = on the current path, 2 = fully explored
    findings: list[str] = []

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for dependency in graph.get(node, []):
            if dependency not in graph or state.get(dependency) == 2:
                continue
            if state.get(dependency) == 1:
                cycle = [*path[path.index(dependency) :], dependency]
                findings.append(f"{PLAN_DOC}: start-dependency cycle: {' -> '.join(cycle)}")
                continue
            visit(dependency, [*path, dependency])
        state[node] = 2

    for identifier in graph:
        if identifier not in state:
            visit(identifier, [identifier])
    return findings


def _task_findings(capabilities: list[Capability], tasks: list[Task]) -> list[str]:
    findings: list[str] = []
    known = {capability.identifier for capability in capabilities}
    identifiers: set[str] = set()
    for task in tasks:
        findings.extend(_task_identity_findings(task, known, identifiers))
        findings.extend(_task_metadata_findings(task))
        findings.extend(_task_status_findings(task))
    return findings


def _section_order_findings(line: list[str], tasks: list[Task], section: str) -> list[str]:
    groups = list(dict.fromkeys(task.group for task in tasks if task.section == section))
    ranked = [line.index(group) for group in groups if group in line]
    if ranked == sorted(ranked):
        return []
    return [f"{PLAN_DOC}: groups in '{section}' do not follow registry order: {groups}"]


def _optional_order_findings(tasks: list[Task], section: str) -> list[str]:
    findings: list[str] = []
    by_group: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        if task.section == section:
            by_group[task.group].append(task)
    for group, group_tasks in by_group.items():
        optional_seen = False
        for task in group_tasks:
            if optional_seen and not task.optional:
                findings.append(
                    f"{PLAN_DOC}: required task `{task.identifier}` follows optional work "
                    f"in `{group}`"
                )
            optional_seen = optional_seen or task.optional
    return findings


def _order_findings(capabilities: list[Capability], tasks: list[Task]) -> list[str]:
    line = [capability.identifier for capability in capabilities]
    findings: list[str] = []
    for section in PLAN_SECTIONS:
        findings.extend(_section_order_findings(line, tasks, section))
        findings.extend(_optional_order_findings(tasks, section))
    return findings


def _plan_text_findings(plan: Path) -> list[str]:
    findings: list[str] = []
    text = plan.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        if _TASK_HEADING.match(line) and not _VALID_TASK_HEADING.match(line):
            findings.append(f"{PLAN_DOC}:{number}: malformed task heading")
        if _HISTORY_WORD.search(line) or _ISO_DATE.search(line):
            findings.append(f"{PLAN_DOC}:{number}: forward plan contains history or a date")
    for section in PLAN_SECTIONS:
        if f"## {section}" not in text:
            findings.append(f"{PLAN_DOC}: missing required lane '{section}'")
    return findings


def recorded_task_ids(project_root: Path, capabilities: list[Capability]) -> set[str]:
    """Return ids of finished tasks that have a record under a registered or `adhoc` group."""
    groups = {capability.identifier for capability in capabilities} | {ADHOC_GROUP}
    return read_recorded_task_ids(project_root / RECORDS_DIR, groups)


def integrity_findings(project_root: Path) -> list[str]:
    """Return every disagreement in the specification-plan contract."""
    spec = project_root / SPEC_DOC
    plan = project_root / PLAN_DOC
    if not spec.is_file() or not plan.is_file():
        missing = [
            str(path) for path in (SPEC_DOC, PLAN_DOC) if not (project_root / path).is_file()
        ]
        return [f"missing required document: {path}" for path in missing]
    capabilities = read_registry(spec)
    if not capabilities:
        return [f"{SPEC_DOC}: no capability registry rows found"]
    tasks = read_tasks(plan)
    return (
        _registry_findings(capabilities, tasks)
        + _task_findings(capabilities, tasks)
        + _dependency_findings(tasks, recorded_task_ids(project_root, capabilities))
        + _order_findings(capabilities, tasks)
        + _plan_text_findings(plan)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the integrity gate."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="check specification and plan integrity")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root else discover_project_root()
    findings = integrity_findings(root)
    for finding in findings:
        _LOG.error("ERROR: %s", finding)
    _LOG.info("[spec-plan] %d finding(s)", len(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
