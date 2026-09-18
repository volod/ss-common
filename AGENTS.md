# AGENTS.md project rules

This file is the canonical instruction source for every coding agent in this repository. Tool-
specific files (`CLAUDE.md`, `GEMINI.md`, `.codex`, `.cursor/rules/project-rules.mdc`) link here
and keep only integration-specific routing.

## Development guardrails

- **Git:** Do not commit, push, rewrite history, or revert user changes unless explicitly asked.
- **Scope:** Preserve unrelated work. Diagnose without changing code when the request is diagnostic.
- **Python:** Support Python 3.11 or newer (Raspberry Pi OS Bookworm ships 3.11). Use `uv`,
  `uv.lock`, and `pyproject.toml` for dependency management. Use Make targets for standard
  workflows. Before a direct `uv` command, source `scripts/shared/common.sh` and run
  `ssc_load_env`.
- **Typing:** Keep production code fully typed. Do not add `from __future__ import annotations`.
- **Paths:** Never hardcode machine-specific absolute paths. Resolve from the project root and
  honor `.env` and `DATA_DIR`; the uv and tool caches live under `$DATA_DIR`.
- **Secrets:** Never commit credentials or include them in logs, tests, fixtures, or documentation.
- **Dependencies:** Add the smallest justified dependency. Update `uv.lock` in the same change.

## Package rules

- One distribution, `ss-common`, with two import packages: `src/ss_contracts/` (message contracts
  and generated models) and `src/ss_kit/` (light runtime helpers). Tests mirror them under
  `tests/`.
- The base install runs on a Raspberry Pi. It never depends on torch, numpy, or transformers,
  directly or transitively; `make footprint` enforces this for `aarch64-unknown-linux-gnu` and
  `x86_64-unknown-linux-gnu`. Integrations go behind the `web`, `mqtt`, `tooling`, or `dev`
  extra and are imported only by the module that needs them.
- Importing `ss_kit` or `ss_contracts` writes nothing to stdout or stderr and configures no
  logging handler.
- Code enters `ss_kit` only when at least two service repositories use it, it holds no domain
  types, and it adds no heavy dependency.
- `src/ss_kit/quality/` holds standard-library gates only, so they run from a bare interpreter.
- Use named constants instead of unexplained literals and `logging` instead of `print()` in
  production code. Aim to keep Python and shell files at or below about 250 lines.
- Runtime output belongs under `$DATA_DIR/<method>/`, never inside `src/`. Shared shell behavior
  belongs in `scripts/shared/common.sh`; every shell function there uses the `ssc_` prefix.

## Tests and quality

- Add or update tests with every behavior change. A bug fix includes a failing regression case.
- Keep tests deterministic. Tests that resolve packages from the index are skipped with
  `SS_OFFLINE=1`; no other test uses the network.
- `make ci` is the required gate: locked install, format check, lint, typing, complexity, shell
  lint, documentation links, spec-plan integrity, dependency footprint, and tests. Fix findings at
  their source; do not weaken checks to fit new code.

## Documentation lifecycle

| Question | Source of truth |
| --- | --- |
| What should the product do? | `docs/design/spec.md` (capability registry, boundaries, evaluation) |
| What work remains? | `docs/impl/plan.md` (forward-only) |
| What exists and where? | `docs/impl/current.md` and `docs/impl/current/` |
| What happened to a finished task? | `docs/impl/records/` |
| How is work performed? | `docs/guide/` and this file |

`docs/impl/plan.md` is FORWARD-ONLY: it contains only work that remains. Delivered behavior lives
under `docs/impl/current/`, indexed by `docs/impl/current.md`.

After every product or developer-facing change, before reporting completion:

1. Record what exists in the narrowest current-state page: behavior, modules, commands, tests,
   verification, and result.
2. Remove the completed task from `docs/impl/plan.md`; retain only residual future work.
3. Route anything surfaced during implementation exactly once: a chore is done now or dropped;
   an audit of the work just produced is performed as part of completion; more work for a
   registered capability becomes a task, `(optional)` when it is a refinement; a new product
   capability follows "Extending this specification" in `docs/design/spec.md` first.
4. Update current-doc indexes when adding a page and run `make lint-doc-links`.
5. Compare plan task counts before and after and state which capabilities moved.

Do not put completion notes, dates, measurements, or history in the plan.

## Task lanes and integrity

The plan has two lanes, **Agent Implementation Tasks** (`CLEAR`, `RUN NEEDED`) and
**Human-Assisted Tasks** (`BLOCKED BY HUMAN`, `HUMAN-GATED`, plus a `Human step` field). Task
fields, ordering, dependencies, and records are defined in the
[planning workflow](docs/guide/planning-workflow.md). `make lint-spec-plan` enforces them; fix
document disagreements when it fails and do not loosen the checker. `make plan-status` names the
next eligible task per lane.

## Completion discipline

Before declaring a plan task complete: keep a task record under `docs/impl/records/`, run the
declared tests and `make ci`, update current docs, remove finished plan scope, and inspect
`git status`. Confirm that only intended files changed and that no process, port, temporary
scaffold, or external resource started by the work remains active. Runtime artifacts under
`DATA_DIR` are evidence; keep them unless the task says otherwise.

Use ASCII in code, logs, comments, documentation, and generated output.
