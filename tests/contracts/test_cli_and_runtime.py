import datetime
import logging
import pathlib
import subprocess
import sys

import pydantic
import pytest

from ss_contracts.base import ContractBytes, ContractModel, ContractTimestamp
from ss_contracts.tooling.cli import main
from ss_contracts.tooling.registry import load_registry

from ._contract_fixture import prop
from .conftest import EditContract

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _run(root: pathlib.Path, *args: str) -> int:
    return main(["--root", str(root), *args])


def test_cli_happy_path(sample_root: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    assert _run(sample_root, "validate") == 0
    assert _run(sample_root, "generate", "--check") == 1  # models not generated yet
    assert _run(sample_root, "generate", "--format", "pydantic", "--format", "avro") == 0
    assert _run(sample_root, "generate", "--check") == 0
    assert _run(sample_root, "evolution-check") == 0
    assert _run(sample_root, "evolution-freeze") == 0
    out = caplog.text
    assert "[contracts] 2 valid" in out
    assert "[contracts] generated 5 files (pydantic, avro)" in out
    assert "[evolution] sample-reading: 1.1.0 -> 1.1.0 (identical) ok" in out
    assert "[evolution] 2 contracts follow the version policy" in out


def test_cli_reports_findings_on_stderr(
    sample_root: pathlib.Path, edit_contract: EditContract, caplog: pytest.LogCaptureFixture
) -> None:
    assert _run(sample_root, "generate", "--format", "pydantic") == 0
    edit_contract("sample-reading", lambda doc: prop(doc, "snr").update(required=True))
    caplog.clear()
    assert _run(sample_root, "generate", "--check") == 1
    assert _run(sample_root, "evolution-check") == 1
    assert _run(sample_root, "evolution-freeze") == 1
    err = caplog.text
    assert "sample_reading.py differs from its contract" in err
    assert "breaking change without a version bump" in err


def test_cli_unusable_registry(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    assert _run(tmp_path, "validate") == 2
    assert "registry.yaml does not exist" in caplog.text


def test_console_script_runs_as_module(sample_root: pathlib.Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ss_contracts.tooling.cli", "--root", str(sample_root), "validate"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (result.stdout, result.stderr) == ("", "[contracts] 2 valid\n")


def test_missing_tooling_extra_is_explained(sample_root: pathlib.Path) -> None:
    probe = (
        "import sys; sys.modules['fastavro'] = None;"
        "from ss_contracts.tooling.cli import main;"
        f"raise SystemExit(main(['--root', {str(sample_root)!r}, 'evolution-check']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "pip install 'ss-common[tooling]' (missing module 'fastavro')" in result.stderr


def test_project_contract_tree_is_clean() -> None:
    """The committed registry, models, and baselines agree (what `make contracts` gates)."""
    root = PROJECT_ROOT / "contracts"
    registry = load_registry(root)
    assert registry.models_dir == PROJECT_ROOT / "src" / "ss_contracts" / "models"
    for command in (["validate"], ["generate", "--check"], ["evolution-check"]):
        assert _run(root, *command) == 0, command


class _Probe(ContractModel):
    blob: ContractBytes
    at: ContractTimestamp


def test_runtime_types_use_the_wire_encodings() -> None:
    probe = _Probe.model_validate_json(
        '{"blob": "AQID_w==", "at": "2026-05-01T12:00:00Z", "new": 1}'
    )
    assert probe.blob == b"\x01\x02\x03\xff"  # URL-safe input is accepted
    assert probe.model_dump_json() == '{"blob":"AQID/w==","at":"2026-05-01T12:00:00Z"}'
    assert probe.model_dump()["blob"] == b"\x01\x02\x03\xff"  # python mode keeps bytes
    assert probe.at.tzinfo == datetime.UTC
    with pytest.raises(pydantic.ValidationError):
        _Probe.model_validate_json('{"blob": "", "at": "2026-05-01T12:00:00"}')


def test_models_package_exports_the_registry() -> None:
    import ss_contracts.models as models

    assert sorted(models.CONTRACTS) == [
        "acoustic-observation",
        "camera-event",
        "event-envelope",
        "scene-caption",
        "sensor-event",
        "sensor-reading",
        "sensor-state",
        "threat-event",
    ]
    assert all(issubclass(model, ContractModel) for model in models.CONTRACTS.values())
    assert models.ContractModel is ContractModel
