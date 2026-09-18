"""Summarize the forward plan and identify the next eligible work in each lane.

Run: `python -m ss_kit.quality.plan_summary [--root DIR]` (or `make plan-status`).

A task is eligible when none of its start dependencies is still an open plan task. The next task
in a lane is the first eligible one in registry order, required work before optional refinements.
"""

import argparse
import logging
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from ss_kit.quality.plan_integrity import PLAN_DOC, SPEC_DOC, integrity_findings
from ss_kit.quality.plan_model import (
    AGENT_SECTION,
    HUMAN_SECTION,
    Task,
    read_registry,
    read_tasks,
)
from ss_kit.quality.project_root import discover_project_root

_LOG = logging.getLogger(__name__)


def open_dependencies(task: Task, open_ids: set[str]) -> list[str]:
    """Return the start dependencies of `task` that are still open in the plan."""
    return [dependency for dependency in task.start_dependencies if dependency in open_ids]


def _ranked(tasks: list[Task], section: str, capability_order: dict[str, int]) -> list[Task]:
    lane = [task for task in tasks if task.section == section]
    return sorted(
        lane,
        key=lambda task: (
            capability_order.get(task.group, len(capability_order)),
            task.optional,
            tasks.index(task),
        ),
    )


def _lane_line(label: str, ranked: list[Task], open_ids: set[str]) -> str:
    if not ranked:
        return f"{label}: none"
    for task in ranked:
        if not open_dependencies(task, open_ids):
            optional = " (optional)" if task.optional else ""
            return f"{label}: {task.identifier}{optional} [{task.group}]"
    first = ranked[0]
    waiting = ", ".join(open_dependencies(first, open_ids))
    return f"{label}: none eligible; first in line `{first.identifier}` waits on {waiting}"


def summary_lines(project_root: Path) -> list[str]:
    """Render a compact status summary after validating the plan."""
    findings = integrity_findings(project_root)
    if findings:
        return ["plan is invalid; run make lint-spec-plan"]

    capabilities = read_registry(project_root / SPEC_DOC)
    tasks = read_tasks(project_root / PLAN_DOC)
    capability_order = {
        capability.identifier: number for number, capability in enumerate(capabilities)
    }
    open_ids = {task.identifier for task in tasks}
    eligible = [task for task in tasks if not open_dependencies(task, open_ids)]
    status_counts = Counter(task.agent_status for task in tasks)
    lines = [
        f"tasks: {len(tasks)}",
        f"agent lane: {sum(task.section == AGENT_SECTION for task in tasks)}",
        f"human lane: {sum(task.section == HUMAN_SECTION for task in tasks)}",
    ]
    if status_counts:
        rendered = ", ".join(
            f"{status}={count}" for status, count in sorted(status_counts.items()) if status
        )
        lines.append(f"statuses: {rendered}")
    lines.append(
        "eligible now: "
        f"agent={sum(task.section == AGENT_SECTION for task in eligible)}, "
        f"human={sum(task.section == HUMAN_SECTION for task in eligible)}"
    )
    for label, section in (("next agent", AGENT_SECTION), ("next human", HUMAN_SECTION)):
        lines.append(_lane_line(label, _ranked(tasks, section, capability_order), open_ids))
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Print plan status for maintainers and agents."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="summarize the forward implementation plan")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root else discover_project_root()
    findings = integrity_findings(root)
    for line in summary_lines(root):
        _LOG.info("%s", line)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
