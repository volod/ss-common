from pathlib import Path

import pytest

from ss_kit.paths import data_dir, data_path, ensure_dir, resolve_under
from ss_kit.settings import (
    KitSettings,
    env_layers,
    is_secret_name,
    load_layered_env,
    mask_secret,
)


def test_mask_secret() -> None:
    assert mask_secret("hf_abcdefghijklmnopqrstuv") == "*********************stuv"
    assert mask_secret("") == "<not set>"
    assert mask_secret("hi") == "*i"
    assert mask_secret("abcd") == "***d"
    assert mask_secret("abcdef", visible_suffix=2) == "****ef"


@pytest.mark.parametrize(
    ("name", "secret"),
    [
        ("API_KEY", True),
        ("HF_TOKEN", True),
        ("COOP_MQTT_PASSWORD", True),
        ("WEBHOOK_SECRET", True),
        ("GCP_CREDENTIALS", True),
        ("KEYFRAME_STRIDE", False),
        ("MONKEY_MODE", False),
        ("MAX_TOKENS", False),
        ("DATA_DIR", False),
    ],
)
def test_secret_names(name: str, secret: bool) -> None:
    assert is_secret_name(name) is secret


def test_data_dir_resolves_against_the_project_root(tmp_path: Path) -> None:
    assert data_dir(tmp_path, {}) == tmp_path / ".data"
    assert data_dir(tmp_path, {"DATA_DIR": "  "}) == tmp_path / ".data"
    assert data_dir(tmp_path, {"DATA_DIR": "var/../store"}) == tmp_path / "store"
    assert data_dir(tmp_path, {"DATA_DIR": "/srv/ss"}) == Path("/srv/ss")
    assert resolve_under(tmp_path, "~/x") == Path.home() / "x"


def test_data_path_stays_below_data_dir(tmp_path: Path) -> None:
    env = {"DATA_DIR": "d"}
    assert data_path(tmp_path, "cache", "uv", environ=env) == tmp_path / "d/cache/uv"
    assert data_path(tmp_path, environ=env) == tmp_path / "d"
    with pytest.raises(ValueError, match="leaves DATA_DIR"):
        data_path(tmp_path, "..", "etc", environ=env)
    made = ensure_dir(tmp_path / "a" / "b")
    assert made.is_dir()


def test_layered_env_order_and_precedence(tmp_path: Path) -> None:
    package_env = tmp_path / "pkg-env"
    package_env.mkdir()
    (package_env / "test.env").write_text("A=pkg\nB=pkg\nC=pkg\nD=pkg\n", encoding="utf-8")
    (tmp_path / ".data").mkdir()
    (tmp_path / ".env").write_text("B=root\nC=root\nD=root\n", encoding="utf-8")
    (tmp_path / ".data/.env").write_text("C=data\nD=data\n", encoding="utf-8")
    (tmp_path / ".data/.env.local").write_text("D=local\nE=local\n", encoding="utf-8")
    environ = {"E": "process"}

    layers = env_layers(tmp_path, app_env="test", package_env_dir=package_env)
    load_layered_env(tmp_path, app_env="test", package_env_dir=package_env, environ=environ)

    assert layers == [
        package_env / "test.env",
        tmp_path / ".env",
        tmp_path / ".data/.env",
        tmp_path / ".data/.env.local",
    ]
    assert environ == {"A": "pkg", "B": "root", "C": "data", "D": "local", "E": "process"}


def test_layers_follow_app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    assert env_layers(tmp_path, package_env_dir=tmp_path)[0] == tmp_path / "prod.env"
    assert env_layers(tmp_path) == [
        tmp_path / name for name in (".env", ".data/.env", ".data/.env.local")
    ]


class _Settings(KitSettings):
    SECRET_FIELDS = frozenset({"DSN"})
    API_KEY = "abcdefgh"
    HF_TOKEN = ""
    DSN = "postgres://u:p@h/db"
    WORKERS = 4
    _PRIVATE = "hidden"
    lower = "ignored"

    def HELPER(self) -> int:
        return 1


def test_settings_mask_secrets_and_resolve_data_dir(tmp_path: Path) -> None:
    settings = _Settings()
    type(settings).PROJECT_ROOT = tmp_path
    try:
        assert settings.fields() == {
            "API_KEY": "abcdefgh",
            "DSN": "postgres://u:p@h/db",
            "HF_TOKEN": "",
            "WORKERS": 4,
        }
        masked = settings.masked()
        assert masked["API_KEY"] == "****efgh"
        assert masked["HF_TOKEN"] == "<not set>"
        assert masked["DSN"].endswith("h/db") and "u:p" not in masked["DSN"]
        assert "abcdefgh" not in repr(settings) and "WORKERS=4" in repr(settings)
        assert settings.data_dir({"DATA_DIR": "x"}) == tmp_path / "x"
    finally:
        type(settings).PROJECT_ROOT = None
