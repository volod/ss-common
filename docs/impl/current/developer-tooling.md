# Developer Tooling

## Package layout

| Path | Holds |
| --- | --- |
| `src/ss_contracts/` | Contract package (`DISTRIBUTION`, `py.typed`); contract content arrives with the contract tasks |
| `src/ss_kit/` | Runtime-helper package: `package_version()`, `py.typed`, and `ss_kit.quality` (spec-plan, doc-link, plan-status, and footprint gates) |
| `tests/` | `test_packages.py` (identity, silent and light import), `quality/` (gate tests) |
| `scripts/shared/common.sh` | `ssc_load_env`: `.env`, `DATA_DIR`, uv and tool caches, uv link mode |

Importing `ss_kit`, `ss_contracts`, or `ss_kit.quality.footprint` writes nothing to stdout or
stderr and loads none of torch, numpy, transformers, or pydantic; `tests/test_packages.py`
asserts this in a fresh interpreter.

## Environment

`pyproject.toml` declares the distribution `ss-common` 0.1.0 (setuptools, `src` layout),
`requires-python = ">=3.11"`, the base dependency `pydantic>=2.7,<3`, and the extras:

| Extra | Dependencies |
| --- | --- |
| `web` | `fastapi>=0.115`, `pyjwt[crypto]>=2.9` |
| `mqtt` | `aiomqtt>=2.3`, `pyyaml>=6.0` |
| `tooling` | `fastavro>=1.9`, `pyarrow>=16`, `pyyaml>=6.0` |
| `dev` | complexipy, mypy, pytest, radon, ruff, shellcheck-py |

`uv.lock` fixes the universal resolution of every extra. `make bootstrap` runs
`uv sync --locked --all-extras --python 3.11` (`PYTHON_VERSION` overrides it). `[tool.ss-split]`
declares `siblings = []`: ss-common reaches no other staged project.

## Make targets

`make ci` = `bootstrap`, then `format-check`, `lint` (Ruff, py311), `typecheck` (strict mypy over
both packages), `complexity-gate` (Radon D or worse, complexipy above 15), `shell-lint-gate`
(`bash -n` and ShellCheck), `lint-doc-links`, `lint-spec-plan`, `footprint`, and `test`.
`ci-github` is an alias. Other targets: `format`, `lock`, `plan-status`, `build` (to
`$DATA_DIR/dist/`). The Makefile unexports `VIRTUAL_ENV`, so an activated outer environment never
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
build outputs.
