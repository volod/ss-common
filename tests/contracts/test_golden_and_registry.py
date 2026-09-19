import json
import pathlib

import pytest

from ss_contracts.tooling.registry import (
    ROOT_ENV,
    RegistryError,
    default_root,
    load_registry,
)
from ss_contracts.tooling.validate import validate

from ._contract_fixture import prop
from .conftest import EditContract

READING_GOLDEN = "golden/sample-reading"


def test_sample_tree_validates(sample_root: pathlib.Path) -> None:
    report = validate(load_registry(sample_root))
    assert report.ok, report.errors
    assert report.contract_ids == ["sample-detection", "sample-reading"]


def _write(root: pathlib.Path, name: str, payload: object) -> None:
    (root / READING_GOLDEN / name).write_text(json.dumps(payload))


def _minimal() -> dict[str, object]:
    return {
        "dev_eui": "a84041000181c061",
        "received_at": "2026-05-01T12:00:00Z",
        "f_cnt": 0,
        "tags": [],
    }


@pytest.mark.parametrize(
    ("name", "payload", "expected"),
    [
        (
            "offset.json",
            {**_minimal(), "received_at": "2026-05-01T12:00:00+00:00"},
            "does not round-trip",
        ),
        ("urlsafe.json", {**_minimal(), "raw_bytes": "AQID_w=="}, "does not round-trip"),
        (
            "naive.json",
            {**_minimal(), "received_at": "2026-05-01T12:00:00"},
            "rejected by the model",
        ),
        ("accepted.invalid.json", _minimal(), "counter-example accepted by the model"),
    ],
)
def test_golden_findings(
    sample_root: pathlib.Path, name: str, payload: object, expected: str
) -> None:
    _write(sample_root, name, payload)
    errors = validate(load_registry(sample_root)).errors
    assert any(name in e and expected in e for e in errors), errors


def test_naive_timestamp_counter_example_is_rejected_by_both(sample_root: pathlib.Path) -> None:
    _write(sample_root, "naive.invalid.json", {**_minimal(), "received_at": "2026-05-01T12:00:00"})
    assert validate(load_registry(sample_root)).ok


def test_every_contract_needs_a_golden_message(sample_root: pathlib.Path) -> None:
    for path in (sample_root / READING_GOLDEN).glob("*.json"):
        if not path.name.endswith(".invalid.json"):
            path.unlink()
    errors = validate(load_registry(sample_root)).errors
    assert "sample-reading [golden]: no golden message" in errors


def test_golden_dir_without_contract_is_reported(sample_root: pathlib.Path) -> None:
    (sample_root / "golden" / "retired").mkdir()
    errors = validate(load_registry(sample_root)).errors
    assert "golden fixtures retired/ have no registered contract" in errors


def test_contract_errors_skip_golden_checks(
    sample_root: pathlib.Path, edit_contract: EditContract
) -> None:
    edit_contract("sample-reading", lambda doc: prop(doc, "snr").update(physicalType="string"))
    errors = validate(load_registry(sample_root)).errors
    assert any("physicalType 'string' cannot carry number" in e for e in errors)
    assert not any("[golden]" in e for e in errors)


def test_unregistered_and_missing_contracts(sample_root: pathlib.Path) -> None:
    (sample_root / "odcs" / "sample-detection.odcs.yaml").rename(
        sample_root / "odcs" / "orphan.odcs.yaml"
    )
    errors = validate(load_registry(sample_root)).errors
    assert any("sample-detection: odcs file" in e and "does not exist" in e for e in errors)
    assert "odcs/orphan.odcs.yaml is not registered" in errors


def test_registry_key_must_match_odcs_id(sample_root: pathlib.Path) -> None:
    registry_file = sample_root / "registry.yaml"
    registry_file.write_text(
        registry_file.read_text().replace("  sample-reading:", "  other-reading:")
    )
    errors = validate(load_registry(sample_root)).errors
    assert "other-reading: ODCS id 'sample-reading' differs from its key" in errors


def test_odcs_path_may_not_leave_the_root(
    sample_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    outside = tmp_path / "outside.odcs.yaml"
    outside.write_text((sample_root / "odcs" / "sample-reading.odcs.yaml").read_text())
    registry_file = sample_root / "registry.yaml"
    registry_file.write_text(
        registry_file.read_text().replace("odcs/sample-reading.odcs.yaml", "../outside.odcs.yaml")
    )
    errors = validate(load_registry(sample_root)).errors
    assert "sample-reading: odcs path leaves the contracts root" in errors


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("registryVersion: 2\n", "registryVersion must be 1"),
        ("registryVersion: 1\ncontracts: []\n", "'contracts' must be a mapping"),
        ("registryVersion: 1\njsonSchemaIdBase: x\ngeneratedDir: g\n", "'modelsDir' must be"),
    ],
)
def test_unusable_registry(tmp_path: pathlib.Path, text: str, expected: str) -> None:
    (tmp_path / "registry.yaml").write_text(text)
    with pytest.raises(RegistryError, match=expected):
        load_registry(tmp_path)


def test_registry_entry_rules(sample_root: pathlib.Path) -> None:
    registry_file = sample_root / "registry.yaml"
    original = registry_file.read_text()
    registry_file.write_text(original.replace("owner: ss-sens", "owner: ''"))
    with pytest.raises(RegistryError, match="'owner'"):
        load_registry(sample_root)
    registry_file.write_text(original.replace("sample-reading.odcs.yaml", "sample-reading.yaml"))
    with pytest.raises(RegistryError, match=r"relative \*\.odcs\.yaml path"):
        load_registry(sample_root)


def test_default_root(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    for marker in ("pyproject.toml", "AGENTS.md"):
        (tmp_path / marker).write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ROOT_ENV, raising=False)
    assert default_root() == tmp_path / "contracts"
    monkeypatch.setenv(ROOT_ENV, "elsewhere/contracts")
    assert default_root() == tmp_path / "elsewhere" / "contracts"
