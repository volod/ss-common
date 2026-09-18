import os
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from ss_kit.quality.footprint import (
    FORBIDDEN,
    PLATFORMS,
    Resolution,
    compile_command,
    findings,
    main,
    normalize,
    parse_pins,
    resolve,
    write_resolutions,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPILED = """\
annotated-types==0.8.0
pydantic==2.13.5
    # via ss-common
Torch==2.9.1+cpu
numpy[extra]==2.3.1 ; sys_platform == 'linux'
"""
network = pytest.mark.skipif(
    os.environ.get("SS_OFFLINE") == "1" or shutil.which("uv") is None,
    reason="resolves from the package index (SS_OFFLINE=1 or no uv)",
)


def test_parse_pins_normalizes_names_and_skips_comments() -> None:
    assert parse_pins(COMPILED) == {
        "annotated-types": "0.8.0",
        "pydantic": "2.13.5",
        "torch": "2.9.1+cpu",
        "numpy": "2.3.1",
    }
    assert normalize("Typing_Extensions") == "typing-extensions"


def test_findings_name_each_forbidden_package_per_platform() -> None:
    heavy = Resolution("x86_64-unknown-linux-gnu", parse_pins(COMPILED), COMPILED)
    light = Resolution("aarch64-unknown-linux-gnu", {"pydantic": "2.13.5"}, "")
    assert findings([heavy, light]) == [
        "x86_64-unknown-linux-gnu: base install resolves forbidden torch==2.9.1+cpu",
        "x86_64-unknown-linux-gnu: base install resolves forbidden numpy==2.3.1",
    ]
    assert findings([light]) == []


def test_resolve_runs_one_compile_per_platform(tmp_path: Path) -> None:
    calls: list[Sequence[str]] = []

    def runner(command: Sequence[str]) -> str:
        calls.append(command)
        return "pydantic==2.13.5\n"

    resolutions = resolve(tmp_path / "pyproject.toml", runner=runner)
    assert [resolution.platform for resolution in resolutions] == list(PLATFORMS)
    assert calls[0] == compile_command("uv", tmp_path / "pyproject.toml", PLATFORMS[0], "3.11")
    assert "--python-platform" in calls[1] and PLATFORMS[1] in calls[1]
    write_resolutions(resolutions, tmp_path / "out")
    assert (tmp_path / "out" / f"base-{PLATFORMS[0]}.txt").read_text() == "pydantic==2.13.5\n"


def test_default_forbidden_set_matches_the_specification() -> None:
    assert set(FORBIDDEN) == {"torch", "numpy", "transformers"}


def _planted(tmp_path: Path, dependency: str) -> Path:
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    anchor = 'dependencies = [\n  "pydantic'
    assert anchor in text
    planted = tmp_path / "pyproject.toml"
    planted.write_text(text.replace(anchor, f'dependencies = [\n  "{dependency}",\n  "pydantic'))
    return planted


@network
def test_repository_base_install_is_light(tmp_path: Path) -> None:
    out = tmp_path / "footprint"
    assert main(["--pyproject", str(PROJECT_ROOT / "pyproject.toml"), "--out", str(out)]) == 0
    for platform in PLATFORMS:
        assert "pydantic==" in (out / f"base-{platform}.txt").read_text()


@network
def test_planted_numpy_dependency_fails_the_gate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert main(["--pyproject", str(_planted(tmp_path, "numpy>=1.26"))]) == 1
    for platform in PLATFORMS:
        assert f"{platform}: base install resolves forbidden numpy==" in caplog.text


@network
def test_transitive_numpy_fails_the_gate(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # pandas is not forbidden itself, but it pulls numpy into the base install.
    assert main(["--pyproject", str(_planted(tmp_path, "pandas>=2.2"))]) == 1
    assert "forbidden numpy==" in caplog.text
