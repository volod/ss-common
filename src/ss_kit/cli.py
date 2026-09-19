"""`ss-kit`: shell entrypoints for the runtime helpers.

```text
ss-kit max-jobs [--ram-per-job-gb G] [--reserve-frac F]   # MAX_JOBS for heavy compiles
ss-kit build-budget [--total-kb N --avail-kb N --cpu-cores N] [--ram-per-job-gb G]
                    [--reserve-frac F]                     # jobs total avail usable mem cpu
ss-kit hw                                                  # detected memory and CPUs as JSON
```
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from ss_kit import hw


def _budget_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ram-per-job-gb",
        type=float,
        default=hw.DEFAULT_RAM_PER_JOB_GB,
        help="estimated peak RAM per compile job in GiB",
    )
    parser.add_argument(
        "--reserve-frac",
        type=float,
        default=hw.DEFAULT_RESERVE_FRAC,
        help="fraction of total RAM kept free",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ss-kit", description="ss runtime helper commands")
    commands = parser.add_subparsers(dest="command", required=True)
    _budget_options(commands.add_parser("max-jobs", help="print a safe MAX_JOBS for this host"))
    budget = commands.add_parser("build-budget", help="print the full compile budget")
    budget.add_argument("--total-kb", type=int, help="MemTotal in KiB (default: detected)")
    budget.add_argument("--avail-kb", type=int, help="MemAvailable in KiB (default: detected)")
    budget.add_argument("--cpu-cores", type=int, help="usable cores (default: detected)")
    _budget_options(budget)
    commands.add_parser("hw", help="print detected memory and CPUs as JSON")
    return parser


def _budget(args: argparse.Namespace) -> hw.BuildBudget:
    memory = hw.memory_info()
    return hw.build_budget(
        args.total_kb if args.total_kb is not None else memory.total_kb,
        args.avail_kb if args.avail_kb is not None else memory.available_kb,
        args.cpu_cores if args.cpu_cores is not None else hw.cpu_count(),
        args.ram_per_job_gb,
        args.reserve_frac,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "max-jobs":
        sys.stdout.write(f"{hw.max_jobs(args.ram_per_job_gb, args.reserve_frac)}\n")
    elif args.command == "build-budget":
        sys.stdout.write(f"{_budget(args).summary()}\n")
    else:
        report = {"memory": asdict(hw.memory_info()), "cpu_count": hw.cpu_count()}
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
