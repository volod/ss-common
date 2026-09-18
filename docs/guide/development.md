# Development Guide

## Setup

Install Git, Make, and uv, then run:

```bash
make bootstrap
make ci
```

`make bootstrap` installs the locked environment with every extra on Python 3.11, the lowest
supported version; pass `PYTHON_VERSION=3.12` (or newer) to test another interpreter. The lockfile
is committed. After changing dependencies in `pyproject.toml`, run `make lock` and include the
resulting `uv.lock` change.

## Quality workflow

`make ci` is the one required gate, locally and in GitHub Actions. It installs the locked
environment, then runs `format-check`, `lint` (Ruff), `typecheck` (mypy), `complexity-gate` (Radon
and complexipy), `shell-lint-gate` (bash and ShellCheck), `lint-doc-links`, `lint-spec-plan`,
`footprint`, and `test`.

`make footprint` resolves the base install (no extras) with `uv pip compile --python-platform` for
`aarch64-unknown-linux-gnu` and `x86_64-unknown-linux-gnu` at Python 3.11 and fails when torch,
numpy, or transformers appear anywhere in the resolution. The pins are kept under
`$DATA_DIR/footprint/`. The gate needs the package index or a warm uv cache. `SS_OFFLINE=1 make
test` skips the tests that resolve from the index.

## Direct uv commands

Make targets are the stable workflow. For one-off dependency debugging:

```bash
source scripts/shared/common.sh
ssc_load_env
uv <command>
```

This loads `.env`, resolves `DATA_DIR` against the project root, moves the uv, Ruff, and mypy
caches below it, and selects `UV_LINK_MODE=copy` only when the uv cache and the checkout live on
different filesystems.

## Runtime artifacts

Generated data goes under `$DATA_DIR/<method>/` (default `.data/`): `footprint/`, `dist/`,
`uv-cache/`, and `cache/`. Keep fixtures under `tests/` only when they are small, deterministic,
safe to publish, and required for CI.
