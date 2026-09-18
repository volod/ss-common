# ss-common developer entrypoints.
SHELL := /bin/bash
PROJECT_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
VENV := $(PROJECT_ROOT)/.venv
PY := $(VENV)/bin/python
# Lowest supported Python (Raspberry Pi OS Bookworm); CI adds newer versions.
PYTHON_VERSION ?= 3.11
DATA_DIR ?= .data
DATA_ROOT := $(if $(filter /%,$(DATA_DIR)),$(DATA_DIR),$(PROJECT_ROOT)/$(DATA_DIR))
PYTEST_CACHE := -o cache_dir=$(DATA_ROOT)/cache/pytest
# Every uv call loads .env and derives UV_CACHE_DIR and the tool caches from DATA_DIR.
ENV := source "$(PROJECT_ROOT)/scripts/shared/common.sh"; ssc_load_env;

# The project always uses its own .venv, never an activated outer one.
unexport VIRTUAL_ENV

export RUFF_CACHE_DIR := $(DATA_ROOT)/cache/ruff
export MYPY_CACHE_DIR := $(DATA_ROOT)/cache/mypy

.DEFAULT_GOAL := help

.PHONY: help bootstrap venv lock format format-check lint typecheck test complexity-gate \
	shell-lint-gate lint-doc-links lint-spec-plan plan-status footprint ci-checks ci ci-github \
	build

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "; print "Usage: make <target>\n"} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Create/update .venv from uv.lock with every extra
	@command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is required"; exit 1; }
	@$(ENV) uv sync --locked --all-extras --python "$(PYTHON_VERSION)"

venv: bootstrap ## Alias for bootstrap

lock: ## Refresh uv.lock after dependency changes
	@$(ENV) uv lock

format: ## Format production code and tests with Ruff
	@"$(VENV)/bin/ruff" format src tests
	@"$(VENV)/bin/ruff" check --fix src tests

format-check: ## Check Python formatting without changing files
	@"$(VENV)/bin/ruff" format --check src tests

lint: ## Run Ruff lint checks
	@"$(VENV)/bin/ruff" check src tests

typecheck: ## Run mypy over production code
	@"$(VENV)/bin/mypy" --python-version "$(PYTHON_VERSION)"

test: ## Run unit tests (SS_OFFLINE=1 skips tests that resolve from the package index)
	@$(ENV) "$(PY)" -m pytest $(PYTEST_CACHE)

complexity-gate: ## Fail on Radon D-or-worse or cognitive complexity above 15
	@output="$$($(VENV)/bin/radon cc src tests -s -n D)"; \
		if [ -n "$$output" ]; then printf '%s\n' "$$output"; exit 1; fi
	@mkdir -p "$(DATA_ROOT)/cache/complexipy"
	@cd "$(DATA_ROOT)/cache/complexipy"; \
		output="$$($(VENV)/bin/complexipy "$(PROJECT_ROOT)/src" "$(PROJECT_ROOT)/tests" \
		--max-complexity-allowed 15 --failed --ignore-complexity --color no --plain --sort desc)"; \
		if [ -n "$$output" ]; then printf '%s\n' "$$output"; exit 1; fi

shell-lint-gate: ## Check every shell script with bash and ShellCheck
	@find scripts -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
	@find scripts -type f -name '*.sh' -print0 | \
		xargs -0 -r "$(VENV)/bin/shellcheck" -x -P SCRIPTDIR -S warning

lint-doc-links: ## Check that relative Markdown links and anchors resolve
	@"$(PY)" -m ss_kit.quality.doc_links --root "$(PROJECT_ROOT)"

lint-spec-plan: ## Check capability registry, task structure, status, and ordering
	@"$(PY)" -m ss_kit.quality.plan_integrity --root "$(PROJECT_ROOT)"

plan-status: ## Count tasks by lane/status and show the next eligible work
	@"$(PY)" -m ss_kit.quality.plan_summary --root "$(PROJECT_ROOT)"

footprint: ## Fail if torch, numpy, or transformers enter the base install (aarch64, x86_64)
	@$(ENV) "$(PY)" -m ss_kit.quality.footprint --pyproject "$(PROJECT_ROOT)/pyproject.toml" \
		--out "$(DATA_ROOT)/footprint"

ci-checks: format-check lint typecheck complexity-gate shell-lint-gate lint-doc-links \
	lint-spec-plan footprint

ci: bootstrap ci-checks test ## Run the required local and GitHub CI gate

ci-github: ci ## Explicit GitHub Actions entrypoint

build: ## Build source and wheel distributions into $(DATA_DIR)/dist
	@$(ENV) uv build --out-dir "$(DATA_ROOT)/dist"
