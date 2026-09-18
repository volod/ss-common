"""Dependency-footprint gate: the base install must stay light enough for the edge tier.

Run: `python -m ss_kit.quality.footprint [--pyproject FILE] [--out DIR]` (or `make footprint`).

Resolves the base dependencies of `pyproject.toml` (no extras) with `uv pip compile` for every
target platform at the lowest supported Python, and fails when a forbidden distribution appears
anywhere in the resolution, direct or transitive. Standard library only.
"""

import argparse
import logging
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)

PLATFORMS = ("aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu")
FORBIDDEN = ("torch", "numpy", "transformers")
PYTHON_VERSION = "3.11"
_PINNED = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*(?P<version>\S+)"
)

Runner = Callable[[Sequence[str]], str]


@dataclass(frozen=True, slots=True)
class Resolution:
    """The pinned base install for one target platform."""

    platform: str
    packages: dict[str, str]
    text: str


def normalize(name: str) -> str:
    """Return the PEP 503 normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(text: str) -> dict[str, str]:
    """Return `{normalized name: version}` from `uv pip compile` output."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        matched = _PINNED.match(line.strip())
        if matched:
            pins[normalize(matched.group("name"))] = matched.group("version")
    return pins


def _run_uv(command: Sequence[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed:\n{result.stderr.strip()}")
    return result.stdout


def compile_command(uv: str, pyproject: Path, platform: str, python_version: str) -> list[str]:
    """Return the `uv pip compile` command that resolves the base install for one platform."""
    return [
        uv,
        "pip",
        "compile",
        str(pyproject),
        "--python-platform",
        platform,
        "--python-version",
        python_version,
        "--no-header",
        "--no-annotate",
        "--quiet",
    ]


def resolve(
    pyproject: Path,
    platforms: Iterable[str] = PLATFORMS,
    python_version: str = PYTHON_VERSION,
    runner: Runner = _run_uv,
    uv: str = "uv",
) -> list[Resolution]:
    """Resolve the base install of `pyproject` for each platform."""
    resolutions: list[Resolution] = []
    for platform in platforms:
        text = runner(compile_command(uv, pyproject, platform, python_version))
        resolutions.append(Resolution(platform, parse_pins(text), text))
    return resolutions


def findings(resolutions: Iterable[Resolution], forbidden: Iterable[str] = FORBIDDEN) -> list[str]:
    """Return one finding per forbidden distribution per platform."""
    banned = [normalize(name) for name in forbidden]
    return [
        f"{resolution.platform}: base install resolves forbidden {name}=="
        f"{resolution.packages[name]}"
        for resolution in resolutions
        for name in banned
        if name in resolution.packages
    ]


def write_resolutions(resolutions: Iterable[Resolution], out: Path) -> None:
    """Keep each resolved base install as `<out>/base-<platform>.txt` evidence."""
    out.mkdir(parents=True, exist_ok=True)
    for resolution in resolutions:
        (out / f"base-{resolution.platform}.txt").write_text(resolution.text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the footprint gate."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="fail when the base install is too heavy")
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--platform", action="append", dest="platforms", default=None)
    parser.add_argument("--forbid", action="append", default=None)
    parser.add_argument("--python-version", default=PYTHON_VERSION)
    parser.add_argument("--out", type=Path, default=None, help="directory for resolved pins")
    args = parser.parse_args(argv)

    uv = shutil.which("uv")
    if uv is None:
        _LOG.error("ERROR: uv is required for the footprint gate")
        return 2
    try:
        resolutions = resolve(
            args.pyproject.resolve(), args.platforms or PLATFORMS, args.python_version, uv=uv
        )
    except RuntimeError as exc:
        _LOG.error("ERROR: %s", exc)
        return 2
    if args.out is not None:
        write_resolutions(resolutions, args.out)
    problems = findings(resolutions, args.forbid or FORBIDDEN)
    for problem in problems:
        _LOG.error("ERROR: %s", problem)
    for resolution in resolutions:
        _LOG.info(
            "[footprint] %s: %d package(s): %s",
            resolution.platform,
            len(resolution.packages),
            ", ".join(sorted(resolution.packages)),
        )
    _LOG.info("[footprint] %d finding(s)", len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
