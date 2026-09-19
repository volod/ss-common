"""Project-root and `DATA_DIR` resolution.

Every runtime path derives from the project root and `DATA_DIR`: a relative `DATA_DIR` resolves
against the project root, never against the current working directory.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from ss_kit.quality.project_root import ROOT_MARKERS, discover_project_root

DATA_DIR_ENV = "DATA_DIR"
DEFAULT_DATA_DIR = ".data"

__all__ = [
    "DATA_DIR_ENV",
    "DEFAULT_DATA_DIR",
    "ROOT_MARKERS",
    "data_dir",
    "data_path",
    "discover_project_root",
    "ensure_dir",
    "resolve_under",
]


def resolve_under(base: Path, value: str | os.PathLike[str]) -> Path:
    """`value` as an absolute path: `~` expanded, relative values joined to `base`."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return Path(os.path.normpath(candidate))


def data_dir(project_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """`$DATA_DIR` resolved against `project_root` (default `.data`)."""
    env = os.environ if environ is None else environ
    raw = env.get(DATA_DIR_ENV, "").strip() or DEFAULT_DATA_DIR
    return resolve_under(project_root, raw)


def data_path(project_root: Path, *parts: str, environ: Mapping[str, str] | None = None) -> Path:
    """A path below `$DATA_DIR`; `parts` must not climb out of it."""
    base = data_dir(project_root, environ)
    target = Path(os.path.normpath(base.joinpath(*parts)))
    if target != base and base not in target.parents:
        raise ValueError(f"{'/'.join(parts)} leaves DATA_DIR")
    return target


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    """Create `path` (and parents) if needed and return it."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
