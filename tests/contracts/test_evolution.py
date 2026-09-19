import json
from collections.abc import Callable
from typing import Any

import pytest

from ss_contracts.tooling.evolution import (
    CHANGE_BACKWARD,
    CHANGE_BREAKING,
    CHANGE_IDENTICAL,
    baseline_path,
    check_evolution,
    classify_change,
    freeze_baselines,
    load_history,
)
from ss_contracts.tooling.registry import Registry

from ._contract_fixture import custom, prop, properties
from .conftest import EditContract

Mutation = Callable[[dict[str, Any]], None]


def _errors(registry: Registry) -> list[str]:
    report = check_evolution(registry)
    return report.errors + [e for item in report.contracts for e in item.errors]


def _with_version(version: str, mutate: Mutation) -> Mutation:
    def apply(doc: dict[str, Any]) -> None:
        doc["version"] = version
        mutate(doc)

    return apply


def _remove(name: str) -> Mutation:
    return lambda doc: properties(doc).remove(prop(doc, name))


def _add(name: str, required: bool, number: int) -> Mutation:
    def apply(doc: dict[str, Any]) -> None:
        properties(doc).append(
            {
                "name": name,
                "logicalType": "string",
                "physicalType": "string",
                "required": required,
                "description": "Added field.",
                "customProperties": [
                    {"property": "fieldGeneration", "value": {"proto": {"fieldNumber": number}}}
                ],
            }
        )

    return apply


def _set_prop(name: str, key: str, value: Any) -> Mutation:
    return lambda doc: prop(doc, name).__setitem__(key, value)


def _set_binding(name: str, key: str, value: str | None) -> Mutation:
    def apply(doc: dict[str, Any]) -> None:
        binding = custom(prop(doc, name), "ssBinding")
        if value is None:
            binding.pop(key)
        else:
            binding[key] = value

    return apply


def _set_number(name: str, number: int) -> Mutation:
    return lambda doc: custom(prop(doc, name), "fieldGeneration")["proto"].update(
        fieldNumber=number
    )


def test_committed_sample_history_passes(registry: Registry) -> None:
    report = check_evolution(registry)
    assert report.ok, _errors(registry)
    detection = next(c for c in report.contracts if c.contract_id == "sample-detection")
    assert detection.history_versions == ["1.0.0", "2.0.0"]
    assert detection.change_class == CHANGE_IDENTICAL


def test_planted_field_removal_without_major_bump_fails(
    registry: Registry, edit_contract: EditContract
) -> None:
    edit_contract("sample-reading", _with_version("1.2.0", _remove("snr")))
    errors = _errors(registry)
    assert any(
        "breaking change needs a major version bump" in e and "removed field 'snr'" in e
        for e in errors
    ), errors

    edit_contract("sample-reading", _with_version("2.0.0", lambda doc: None))
    assert _errors(registry) == []


CASES: dict[str, tuple[Mutation, str, str]] = {
    # name: (mutation, version that passes, change class)
    "added optional": (_add("note", False, 20), "1.2.0", CHANGE_BACKWARD),
    "added required": (_add("note", True, 20), "2.0.0", CHANGE_BREAKING),
    "removed": (_remove("snr"), "2.0.0", CHANGE_BREAKING),
    "kind": (_set_prop("snr", "physicalType", "double"), "2.0.0", CHANGE_BREAKING),
    "requiredness": (_set_prop("snr", "required", True), "2.0.0", CHANGE_BREAKING),
    "proto number": (_set_number("snr", 30), "2.0.0", CHANGE_BREAKING),
    "unit changed": (_set_binding("snr", "unit", "dBm"), "2.0.0", CHANGE_BREAKING),
    "unit removed": (_set_binding("snr", "unit", None), "2.0.0", CHANGE_BREAKING),
    "binding added": (_set_binding("snr", "modality", "lorawan"), "1.2.0", CHANGE_BACKWARD),
    "constraint": (
        _set_prop("f_cnt", "logicalTypeOptions", {"minimum": 1}),
        "1.2.0",
        CHANGE_BACKWARD,
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_change_classes_and_required_bumps(
    registry: Registry, edit_contract: EditContract, case: str
) -> None:
    mutate, passing, change_class = CASES[case]
    edit_contract("sample-reading", mutate)
    item = next(c for c in check_evolution(registry).contracts if c.contract_id == "sample-reading")
    assert item.change_class == change_class
    assert any("without a version bump" in e for e in item.errors), item.errors
    if change_class == CHANGE_BREAKING:
        edit_contract("sample-reading", _with_version("1.2.0", lambda doc: None))
        assert any("needs a major version bump" in e for e in _errors(registry))
    edit_contract("sample-reading", _with_version(passing, lambda doc: None))
    assert _errors(registry) == []


def test_description_edits_are_invisible(registry: Registry, edit_contract: EditContract) -> None:
    edit_contract("sample-reading", _set_prop("snr", "description", "Reworded."))
    assert _errors(registry) == []


def test_version_may_not_go_backwards(registry: Registry, edit_contract: EditContract) -> None:
    edit_contract("sample-reading", _with_version("1.0.9", lambda doc: None))
    assert any("version went backwards" in e for e in _errors(registry))


def test_proto_number_reuse_fails_even_with_a_major_bump(
    registry: Registry, edit_contract: EditContract
) -> None:
    def reuse(doc: dict[str, Any]) -> None:
        custom(doc["schema"][0], "schemaGeneration")["proto"].pop("reserved")
        _add("area_px", False, 3)(doc)

    edit_contract("sample-detection", _with_version("3.0.0", reuse))
    errors = _errors(registry)
    assert any("proto field number 3 was 'score' in 1.0.0" in e for e in errors), errors


def test_missing_and_stale_baselines_fail(registry: Registry) -> None:
    baseline_path(registry, "sample-reading").rename(registry.evolution_dir / "retired.json")
    errors = _errors(registry)
    assert any("sample-reading: no committed baseline" in e for e in errors)
    assert any("baseline retired.json has no registered contract" in e for e in errors)


def test_baseline_without_history_fails(registry: Registry) -> None:
    baseline_path(registry, "sample-reading").write_text(json.dumps({"version": "1.1.0"}))
    assert any("a baseline without history" in e for e in _errors(registry))


def test_tampered_history_step_fails(registry: Registry) -> None:
    path = baseline_path(registry, "sample-detection")
    document = json.loads(path.read_text())
    document["history"][1]["version"] = "1.1.0"
    path.write_text(json.dumps(document))
    errors = _errors(registry)
    assert any(e.startswith("history: sample-detection: breaking change") for e in errors), errors


def test_freeze_is_idempotent(registry: Registry) -> None:
    before = {p.name: p.read_text() for p in registry.evolution_dir.glob("*.json")}
    written, errors = freeze_baselines(registry)
    assert errors == [] and len(written) == 2
    assert {p.name: p.read_text() for p in registry.evolution_dir.glob("*.json")} == before


def test_freeze_appends_a_reviewed_step(registry: Registry, edit_contract: EditContract) -> None:
    edit_contract("sample-reading", _with_version("1.2.0", _add("note", False, 20)))
    assert freeze_baselines(registry)[1] == []
    history = load_history(registry, "sample-reading")
    assert history is not None
    assert [h["version"] for h in history] == ["1.0.0", "1.1.0", "1.2.0"]
    assert _errors(registry) == []


def test_freeze_refuses_a_policy_violation(registry: Registry, edit_contract: EditContract) -> None:
    before = baseline_path(registry, "sample-reading").read_text()
    edit_contract("sample-reading", _remove("snr"))
    written, errors = freeze_baselines(registry)
    assert written == [] and errors
    assert baseline_path(registry, "sample-reading").read_text() == before


def test_freeze_records_new_and_prunes_stale(registry: Registry) -> None:
    baseline_path(registry, "sample-reading").unlink()
    (registry.evolution_dir / "retired.json").write_text("{}")
    assert freeze_baselines(registry)[1] == []
    history = load_history(registry, "sample-reading")
    assert history is not None and [h["version"] for h in history] == ["1.1.0"]
    assert not (registry.evolution_dir / "retired.json").exists()


def test_classify_change_orders_details_deterministically() -> None:
    old = {"fields": {"a": {"required": True}, "b": {"required": True}}, "binding": {}}
    new = {"fields": {"c": {"required": False}, "d": {"required": False}}, "binding": {}}
    report = classify_change(old, new)
    assert report.details == [
        "removed field 'a'",
        "removed field 'b'",
        "added optional field 'c'",
        "added optional field 'd'",
    ]
