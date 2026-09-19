# ss-common Specification

## Purpose

ss-common is the one small shared package of the ss services. It lets ss-sens, ss-control,
ss-video, and ss-fusion agree on messages and reuse light runtime helpers without importing each
other, and it stays light enough to install on a Raspberry Pi next to the sensor mesh.

The specification is living. A need discovered during implementation expands it through
[Extending this specification](#extending-this-specification).

## Scope

One distribution, `ss-common`, with two import packages:

- `ss_contracts`: cross-service message contracts authored as ODCS v3 YAML, a registry, reviewed
  evolution snapshots, and generated Pydantic models committed in the package, so a git-tag
  install needs no generation step.
- `ss_kit`: runtime helpers that at least two service repositories use, and the
  standard-library quality gates (`ss_kit.quality`) every ss repository runs.

Extras: `web` (FastAPI dependencies, security headers, JWT validation), `mqtt` (TLS and mTLS
client settings, topic builder), `tooling` (contract validation and generation), and `dev`
(tests and linters).

**Boundary.** No domain logic, no service settings classes, no GPU or torch helpers, and no torch,
numpy, or transformers in the base install. A contract library shared with fl-op is out of scope.

## Reproducible environment

`pyproject.toml` declares Python 3.11+ metadata and the extras; the committed `uv.lock` fixes the
full resolution. `make ci` installs the locked environment with every extra and runs the same gate
locally, in GitHub Actions, and in the staging repository's isolated split check.
`scripts/shared/common.sh` resolves `DATA_DIR` and keeps the uv and tool caches below it.

Boundary: the project controls Python dependencies and checks. It does not install system
packages or provision services.

Evaluation: a fresh copy with no environment reaches `uv sync --locked` and `make ci` without
manual repair. A negative result names the missing command, stale lock, unsupported interpreter,
or failing gate.

## Base footprint

The base install is what an edge host (Raspberry Pi OS Bookworm, aarch64, Python 3.11) receives
when a service depends on `ss-common` without extras. `make footprint` resolves it with
`uv pip compile --python-platform` for `aarch64-unknown-linux-gnu` and `x86_64-unknown-linux-gnu`
and fails if torch, numpy, or transformers appear, directly or transitively.

Boundary: the gate checks the resolution, not wheel availability or install size on the device.

Evaluation: the gate passes over the tree and fails on a planted numpy dependency and on a
dependency that pulls numpy transitively. Valid negative result: a helper that needs a heavy
dependency moves behind an extra or stays in its service.

## Documentation integrity

`AGENTS.md` is the canonical contributor policy; tool files are adapters. The specification,
forward plan, current-state tree, and task records have distinct ownership. `ss_kit.quality`
validates relative links and anchors, capability registration, task metadata, lane statuses,
group order, dependencies, and forward-only plan language.

Boundary: the checks establish structural agreement, not whether a capability is valuable.

Evaluation: synthetic fixtures reproduce each failure; the tree passes the same checks.

## Staged work

While ss-common is staged in the
[selfsuvis repository](https://github.com/volod/selfsuvis/tree/main/projects/ss-common), its
forward work is the `shared-foundation` group of that repository's plan: ODCS contract tooling,
site-event contracts, mission and model-artifact manifests, and the `ss_kit` runtime helpers.
Those capabilities enter this registry, and their tasks this plan, when ss-common is published. The
ODCS contract tooling, the site-event contracts, and the MQTT topic map already work here and are
described under [current contracts](../impl/current/contracts.md).

## Capability Registry

Every capability appears here exactly once. Status is `planned` when the capability is specified
and has open plan work, or `shipped` when current-state documentation describes it. Row order is
the implementation line.

| # | Capability | Status | How it is evaluated | Implementation |
| --- | --- | --- | --- | --- |
| 1 | `reproducible-environment` | shipped | A fresh copy reaches `uv sync --locked` and `make ci` without manual repair | [Developer tooling](../impl/current/developer-tooling.md) |
| 2 | `base-footprint` | shipped | Base resolution for aarch64 and x86_64 has no torch, numpy, or transformers; planted numpy fails | [Developer tooling](../impl/current/developer-tooling.md#base-footprint) |
| 3 | `documentation-integrity` | shipped | Link and spec-plan checks pass over fixtures and the tree | [Governance](../impl/current/governance.md) |

## Extending this specification

A capability gap is a product discovery, not an automatic refusal and not permission for silent
scope growth. Use this lifecycle in order:

1. State the problem in operator or domain terms.
2. Amend the owning section of this specification, including what the capability does not do.
3. Declare the measurement, acceptance signal, and valid negative result before implementation.
4. Add a `planned` registry row with that evaluation.
5. Put tasks under the capability in the implementation line; every task declares `Serves`.
6. Build and evaluate, document available behavior under current state, remove finished plan
   scope, and change the registry row to `shipped` with its implementation link.
