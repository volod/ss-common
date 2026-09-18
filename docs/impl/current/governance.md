# Governance

## One rules source

`AGENTS.md` carries the development, package, documentation, task, and completion rules.
`CLAUDE.md`, `GEMINI.md`, `.codex`, and `.cursor/rules/project-rules.mdc` are thin adapters that
point to it.

## Specification, plan, and current state

`docs/design/spec.md` owns capabilities, boundaries, evaluations, and registry order;
`docs/impl/plan.md` owns only work that remains, in an agent lane and a human lane; this tree owns
available behavior; `docs/impl/records/` keeps each finished task with its evidence. The
[planning workflow](../../guide/planning-workflow.md) defines task fields, dependencies, ordering,
and record naming.

While ss-common is staged in the selfsuvis repository, its forward work stays in that
repository's plan and this plan has no open tasks (see
[Staged work](../../design/spec.md#staged-work)).

## Checks

Standard-library modules in `src/ss_kit/quality/`, so they run from a bare interpreter:

| Command | Module | Enforces |
| --- | --- | --- |
| `make lint-spec-plan` | `plan_integrity.py` (with `plan_model.py`) | Registry rows (status, evaluation, shipped link, planned has open work); every task in a lane and under the group it serves, with all fields; lane statuses and the `Human step` field; group order; required before `(optional)`; well-formed headings; no history words or dates in the plan; dependencies name open tasks or recorded finished tasks, without start cycles |
| `make lint-doc-links` | `doc_links.py` | Every relative link and `#anchor` in `docs/**/*.md`, `README.md`, `AGENTS.md`, the tool adapters, and `.cursor/**/*.mdc` resolves |
| `make plan-status` (`ss-plan`) | `plan_summary.py` | Refuses an invalid plan; prints counts by lane and status and the next eligible task per lane |

`project_root.py` finds the root by `pyproject.toml` plus `AGENTS.md`. The modules are the
selfsuvis `src/selfsuvis/scripts/quality/` checks (themselves ported from agent-py) under the
`ss_kit.quality` package; they are one implementation for every ss repository.

**Tests.** `tests/quality/` builds synthetic specifications and plans (`_plan_fixture.py`) and
reproduces each failure: unknown capability, misfiled task, missing field, wrong lane status,
missing or misplaced `Human step`, group order, required after optional, duplicate id, history and
dates, unknown dependency, dependency cycle, broken link, and broken anchor. The same tests assert
that this tree passes.
