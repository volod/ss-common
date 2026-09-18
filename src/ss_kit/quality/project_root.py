"""Project-root discovery without machine-specific paths."""

from pathlib import Path

ROOT_MARKERS = ("pyproject.toml", "AGENTS.md")


def discover_project_root(start: Path | None = None) -> Path:
    """Find the nearest ancestor carrying the project markers."""
    candidate = (start or Path.cwd()).resolve()
    for directory in (candidate, *candidate.parents):
        if all((directory / marker).is_file() for marker in ROOT_MARKERS):
            return directory
    markers = ", ".join(ROOT_MARKERS)
    raise FileNotFoundError(f"no project root containing {markers} above {candidate}")
