"""`ss-contracts`: validate, generate, and gate the evolution of the ODCS contracts.

    ss-contracts [--root DIR] validate
    ss-contracts [--root DIR] generate [--format FMT ...] [--check]
    ss-contracts [--root DIR] evolution-check
    ss-contracts [--root DIR] evolution-freeze

`--root` is the directory holding `registry.yaml` (default `$SS_CONTRACTS_ROOT`, else
`contracts/` under the project root). Exit codes: 0 clean, 1 findings, 2 unusable registry or
missing `tooling` extra; `validate` also checks `topics.yaml` next to the registry and exits 2
when that map is unusable.
"""

import argparse
import logging
import pathlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ss_contracts.tooling.types import FORMATS

if TYPE_CHECKING:
    from ss_contracts.tooling.registry import Registry

_LOG = logging.getLogger(__name__)

TOOLING_HINT = "ss-contracts needs the tooling extra: pip install 'ss-common[tooling]'"
# Top-level modules the `tooling` extra provides.
TOOLING_MODULES: frozenset[str] = frozenset(
    {"fastavro", "google", "grpc_tools", "jsonschema", "pyarrow", "yaml"}
)


def _fail(errors: Sequence[str]) -> int:
    for error in errors:
        _LOG.error("ERROR: %s", error)
    return 1 if errors else 0


def _cmd_validate(registry: "Registry", args: argparse.Namespace) -> int:
    from ss_contracts.tooling.validate import validate

    report = validate(registry)
    if report.ok:
        topics = "" if report.topic_count is None else f", {report.topic_count} topics mapped"
        _LOG.info("[contracts] %d valid%s", len(report.contract_ids), topics)
    return _fail(report.errors)


def _cmd_generate(registry: "Registry", args: argparse.Namespace) -> int:
    from ss_contracts.tooling.generate import generate

    formats = args.format or list(FORMATS)
    report = generate(registry, formats, check=args.check)
    if report.ok:
        if args.check:
            _LOG.info("[contracts] models up to date in %s", registry.models_dir)
        else:
            _LOG.info(
                "[contracts] generated %d files (%s)", len(report.written), ", ".join(formats)
            )
    return _fail(report.errors + report.drift)


def _cmd_evolution_check(registry: "Registry", args: argparse.Namespace) -> int:
    from ss_contracts.tooling.evolution import check_evolution

    report = check_evolution(registry)
    for item in report.contracts:
        status = "ok" if item.ok else "FAIL"
        _LOG.info(
            "[evolution] %s: %s -> %s (%s) %s",
            item.contract_id,
            item.baseline_version,
            item.current_version,
            item.change_class,
            status,
        )
    errors = report.errors + [error for item in report.contracts for error in item.errors]
    if not errors:
        _LOG.info("[evolution] %d contracts follow the version policy", len(report.contracts))
    return _fail(errors)


def _cmd_evolution_freeze(registry: "Registry", args: argparse.Namespace) -> int:
    from ss_contracts.tooling.evolution import freeze_baselines

    written, errors = freeze_baselines(registry)
    if not errors:
        _LOG.info(
            "[evolution] recorded %d baselines under %s", len(written), registry.evolution_dir
        )
    return _fail(errors)


_COMMANDS = {
    "validate": _cmd_validate,
    "generate": _cmd_generate,
    "evolution-check": _cmd_evolution_check,
    "evolution-freeze": _cmd_evolution_freeze,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ss-contracts", description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=pathlib.Path, help="directory holding registry.yaml")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "validate", help="validate contracts, generation hints, and golden fixtures"
    )
    gen = commands.add_parser("generate", help="generate models and schemas")
    gen.add_argument("--format", action="append", choices=FORMATS, help="repeatable; default all")
    gen.add_argument("--check", action="store_true", help="fail if committed models are stale")
    commands.add_parser("evolution-check", help="enforce the version-bump policy")
    commands.add_parser("evolution-freeze", help="record reviewed baselines")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    try:
        from ss_contracts.tooling.registry import RegistryError, load_registry
        from ss_contracts.tooling.topics import TopicMapError

        registry = load_registry(args.root)
        return _COMMANDS[args.command](registry, args)
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in TOOLING_MODULES:
            raise
        _LOG.error("ERROR: %s (missing module '%s')", TOOLING_HINT, exc.name)
    except (RegistryError, TopicMapError, FileNotFoundError) as exc:
        _LOG.error("ERROR: %s", exc)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
