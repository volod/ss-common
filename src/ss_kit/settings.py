"""Settings base: layered `.env` loading, `DATA_DIR`, and secret masking.

Service settings are flat classes whose attributes read the environment when the class body runs,
so the layered `.env` files are loaded first (`load_layered_env`), then the class is defined:

```python
root = discover_project_root(Path(__file__).parent)
load_layered_env(root, package_env_dir=Path(__file__).parent / "env")

class Settings(KitSettings):
    PROJECT_ROOT = root
    API_KEY = env_str("API_KEY", "")
```

Layer order, lowest precedence first (the process environment always wins):

1. `<package_env_dir>/<APP_ENV>.env` -- packaged defaults (optional);
2. `<root>/.env` -- user overrides;
3. `<root>/.data/.env` -- stack environment;
4. `<root>/.data/.env.local` -- machine-local overrides, never committed.
"""

import os
import re
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from ss_kit.env import load_env_files
from ss_kit.paths import data_dir

APP_ENV_VAR = "APP_ENV"
DEFAULT_APP_ENV = "dev"
ROOT_ENV_FILES: tuple[str, ...] = (".env", ".data/.env", ".data/.env.local")
NOT_SET = "<not set>"
# Attribute names that hold credentials; `KitSettings.masked()` never shows their values.
SECRET_NAME_RE = re.compile(
    r"(^|_)(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?)(_|$)", re.IGNORECASE
)
_BASE_FIELDS = frozenset({"PROJECT_ROOT", "SECRET_FIELDS"})


def mask_secret(value: str, visible_suffix: int = 4) -> str:
    """`value` with all but the last `visible_suffix` characters replaced by `*`.

    `mask_secret("")` is `<not set>`; a value no longer than the suffix keeps one character.
    """
    if not value:
        return NOT_SET
    if len(value) <= visible_suffix:
        return "*" * (len(value) - 1) + value[-1]
    return "*" * (len(value) - visible_suffix) + value[-visible_suffix:]


def env_layers(
    project_root: Path,
    *,
    app_env: str | None = None,
    package_env_dir: Path | None = None,
    root_env_files: Sequence[str] = ROOT_ENV_FILES,
) -> list[Path]:
    """The `.env` files to apply, lowest precedence first (absent files included)."""
    name = app_env or os.getenv(APP_ENV_VAR, DEFAULT_APP_ENV)
    layers = [package_env_dir / f"{name}.env"] if package_env_dir is not None else []
    layers.extend(project_root / relative for relative in root_env_files)
    return layers


def load_layered_env(
    project_root: Path,
    *,
    app_env: str | None = None,
    package_env_dir: Path | None = None,
    root_env_files: Sequence[str] = ROOT_ENV_FILES,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Apply the layered `.env` files without overriding the environment; returns what was set."""
    layers = env_layers(
        project_root,
        app_env=app_env,
        package_env_dir=package_env_dir,
        root_env_files=root_env_files,
    )
    return load_env_files(layers, environ=environ)


def is_secret_name(name: str) -> bool:
    return SECRET_NAME_RE.search(name) is not None


class KitSettings:
    """Base for flat settings namespaces with upper-case attributes.

    `PROJECT_ROOT` anchors `data_dir()`; `SECRET_FIELDS` adds names to the credential pattern.
    """

    PROJECT_ROOT: ClassVar[Path | None] = None
    SECRET_FIELDS: ClassVar[frozenset[str]] = frozenset()

    def fields(self) -> dict[str, Any]:
        """Every upper-case, non-callable attribute visible on the instance."""
        values: dict[str, Any] = {}
        for name in sorted(dir(self)):
            if name.startswith("_") or not name.isupper() or name in _BASE_FIELDS:
                continue
            value = getattr(self, name)
            if not callable(value):
                values[name] = value
        return values

    def is_secret(self, name: str) -> bool:
        return name in self.SECRET_FIELDS or is_secret_name(name)

    def masked(self) -> dict[str, Any]:
        """`fields()` with every credential value masked; safe to log."""
        return {
            name: mask_secret(str(value or "")) if self.is_secret(name) else value
            for name, value in self.fields().items()
        }

    def data_dir(self, environ: Mapping[str, str] | None = None) -> Path:
        """`$DATA_DIR` resolved against `PROJECT_ROOT` (the working directory when unset)."""
        return data_dir(self.PROJECT_ROOT or Path.cwd(), environ)

    def __repr__(self) -> str:
        body = ", ".join(f"{name}={value!r}" for name, value in self.masked().items())
        return f"{type(self).__name__}({body})"
