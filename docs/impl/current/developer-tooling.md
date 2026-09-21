# Developer Tooling

## Package layout

| Path | Holds |
| --- | --- |
| `src/ss_contracts/` | Contract package: `base` (runtime model base and wire types), committed `models/`, and `tooling/` (the `ss-contracts` CLI); see [contracts](contracts.md) |
| `contracts/` | Contract registry, ODCS sources, MQTT topic map (`topics.yaml`), evolution baselines; `contracts/generated/` is gitignored |
| `src/ss_kit/` | Runtime-helper package: env, settings, paths, logging, security, sidecar, hardware, `web`/`mqtt` extras, `package_version()`, `py.typed`, and `ss_kit.quality`; see [kit](kit.md) |
| `tests/` | `test_packages.py` (identity, silent and light import), `kit/` (runtime helpers), `quality/` (gate tests), `contracts/` (contract tooling), `fixtures/contracts/` (sample tree, golden messages, and golden manifests) |
| `scripts/shared/common.sh` | `ssc_load_env`: `.env`, `DATA_DIR`, uv and tool caches, uv link mode |

Importing `ss_kit`, `ss_contracts`, `ss_kit.quality.footprint`, and the stdlib kit modules
(`env`, `settings`, `paths`, `logging`, `security`, `hw`, `sidecar`, `mqtt`, `ss_contracts.topics`)
writes nothing to stdout or stderr and loads none of torch, numpy, transformers, or pydantic;
`tests/test_packages.py` asserts this in a fresh interpreter. `ss_kit.web` needs the `web` extra.

## Environment

`pyproject.toml` declares the distribution `ss-common` 0.2.1 (setuptools, `src` layout),
`requires-python = ">=3.11"`, the base dependency `pydantic>=2.9,<3` (JSON base64 bytes
validation), the console scripts `ss-contracts`, `ss-kit`, and `ss-plan`, and the extras:

| Extra | Dependencies |
| --- | --- |
| `web` | `fastapi>=0.115`, `httpx>=0.27` (HTTP sidecar client), `pyjwt[crypto]>=2.9` |
| `mqtt` | `aiomqtt>=2.3`, `pyyaml>=6.0` |
| `tooling` | `fastavro>=1.9`, `grpcio-tools>=1.66` (bundled protoc), `jsonschema>=4.18`, `pyarrow>=16`, `pyyaml>=6.0` |
| `dev` | complexipy, mypy, pytest, radon, ruff, shellcheck-py, types-jsonschema, types-pyyaml |

`uv.lock` fixes the universal resolution of every extra. `make bootstrap` runs
`uv sync --locked --all-extras --python 3.11` (`PYTHON_VERSION` overrides it). `[tool.ss-split]`
declares `siblings = []`: ss-common reaches no other staged project.

The README's consumer source example pins `v0.2.1`, matching `pyproject.toml`, `uv.lock`, and
the installed-version assertion in `tests/test_packages.py`. Release preparation passed
`make ci` (287 tests, two upstream warnings) and `make build`; the wheel and source archive
report 0.2.1, with Python >=3.11 and only pydantic in the base requirements. The local release
commit and tag are pending explicit commit authorization; consumers need the tag on the Git
remote. Review scope and evidence are in the [runtime review record](../records/0001-runtime-quality-review.md#follow-up-release-review).

## Make targets

`make ci` = `bootstrap`, then `format-check`, `lint` (Ruff, py311), `typecheck` (strict mypy over
both packages), `complexity-gate` (Radon D or worse, complexipy above 15), `shell-lint-gate`
(`bash -n` and ShellCheck), `lint-doc-links`, `lint-spec-plan`, `footprint`, `contracts`,
`contracts-gen`, `evolution-check`, and `test`.
`ci-github` is an alias. Other targets: `format`, `lock`, `plan-status`, `evolution-freeze`,
`build` (to `$DATA_DIR/dist/`). The contract targets are described in [contracts](contracts.md#commands). The Makefile unexports `VIRTUAL_ENV`, so an activated outer environment never
leaks into the project's `.venv`.

## Base footprint

`python -m ss_kit.quality.footprint` (`make footprint`) runs `uv pip compile pyproject.toml
--python-platform <platform> --python-version 3.11 --no-header --no-annotate` for
`aarch64-unknown-linux-gnu` and `x86_64-unknown-linux-gnu`, parses the pins (PEP 503 names),
fails with one finding per forbidden distribution and platform (`torch`, `numpy`,
`transformers`; `--forbid` overrides), and writes the pins to
`$DATA_DIR/footprint/base-<platform>.txt`. Exit codes: 0 clean, 1 findings, 2 uv missing or the
resolution failed.

`tests/quality/test_footprint.py` covers parsing, findings, and the per-platform commands with a
fake runner, and, against the package index (skipped with `SS_OFFLINE=1`), the tree passing, a
planted `numpy>=1.26` failing on both platforms, and a planted `pandas>=2.2` failing through its
transitive numpy.

## CI

`.github/workflows/ci.yml` runs `make ci-github` on Python 3.11, 3.12, and 3.13 on push to `main`,
on `v*` tags, and on pull requests. While staged, the selfsuvis root CI runs the static split
gates, `uv sync --locked`, and `make -C projects/ss-common ci` for changes under this directory.

## Artifact paths

`.env.example` declares `DATA_DIR=.data`; relative values resolve against the project root. The
uv cache (`$DATA_DIR/uv-cache`), Ruff, mypy, pytest, and complexipy caches, footprint pins, and
build output stay below it. `.gitignore` excludes `.venv/`, `.data/`, `.env`, caches, and root
build outputs, and `contracts/generated/`.
