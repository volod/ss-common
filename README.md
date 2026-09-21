# ss-common

Shared contracts and light runtime helpers for the ss services (ss-sens, ss-control, ss-video,
ss-fusion). One distribution, `ss-common`, ships two import packages:

- `ss_contracts` -- cross-service message contracts, authored as ODCS v3 YAML and generated to
  Pydantic models, JSON Schema, Protobuf, and Avro or Parquet;
- `ss_kit` -- env and settings base, paths, logging, security, sidecar client, and hardware
  detection, plus the standard-library quality gates in `ss_kit.quality`.

The base install depends only on pydantic, so it runs on a Raspberry Pi (Python 3.11+). Heavier
integrations are extras: `web` (FastAPI, httpx, JWT), `mqtt` (aiomqtt, topic builder), `tooling`
(contract generation), and `dev` (tests and linters).

Status: staged inside the selfsuvis repository under `projects/ss-common/` until it is exported
with its history; see the [specification](docs/design/spec.md) and
[current state](docs/impl/current.md).

## Install

```toml
# consumer pyproject.toml
dependencies = ["ss-common[web]"]

[tool.uv.sources]
ss-common = { git = "https://github.com/volod/ss-common", tag = "v0.2.1" }
```

While staged, sibling projects use `ss-common = { path = "../ss-common" }`.

The example pins release `v0.2.1`, matching package version `0.2.1`. The tag must be available
on the Git remote before consumers can install it.
The runtime fixes and migration behavior are described in [runtime helpers](docs/impl/current/kit.md).

## Develop

Requirements: Git, Make, and [uv](https://docs.astral.sh/uv/).

| Command | Purpose |
| --- | --- |
| `make bootstrap` | Create `.venv` from `uv.lock` with every extra (Python 3.11 by default) |
| `make ci` | The required gate: bootstrap, format, lint, typing, complexity, shell lint, doc links, spec-plan integrity, footprint, tests |
| `make footprint` | Fail if torch, numpy, or transformers enter the base install for aarch64 or x86_64 Linux |
| `make test` | Unit tests (`SS_OFFLINE=1` skips the ones that resolve from the package index) |
| `make plan-status` | Task counts and the next eligible task per lane |
| `make lock` | Refresh `uv.lock` after dependency changes |
| `make build` | Source and wheel distributions under `$DATA_DIR/dist/` |

Project rules for people and coding agents: [AGENTS.md](AGENTS.md). Development details:
[development guide](docs/guide/development.md).
