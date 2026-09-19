import pathlib
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from ss_contracts.tooling.odcs import ContractError, load_contract, parse_contract

from ._contract_fixture import SAMPLE, custom, prop, properties

READING = SAMPLE / "odcs" / "sample-reading.odcs.yaml"
Mutation = Callable[[dict[str, Any]], None]


def _doc() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(READING.read_text(encoding="utf-8"))
    return doc


def _errors(mutate: Mutation) -> list[str]:
    doc = _doc()
    mutate(doc)
    with pytest.raises(ContractError) as info:
        parse_contract(doc, READING)
    return info.value.errors


def test_sample_contract_normalizes() -> None:
    spec = load_contract(READING)
    assert (spec.contract_id, spec.version, spec.name) == (
        "sample-reading",
        "1.1.0",
        "sample_reading",
    )
    assert spec.binding["mqttTopic"] == "ss/v1/site/{site_id}/sensor/{dev_eui}/reading"
    kinds = {fld.name: fld.kind for fld in spec.fields}
    assert kinds["rssi"] == "int"  # `integer` alias
    assert kinds["motion"] == "boolean"  # `bool` alias
    position = next(fld for fld in spec.fields if fld.name == "position")
    assert (position.item_kind, dict(position.binding)) == ("double", {"frame": "wgs84"})


def _set(path: tuple[Any, ...], value: Any) -> Mutation:
    def mutate(doc: dict[str, Any]) -> None:
        target: Any = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _set_prop(name: str, key: str, value: Any) -> Mutation:
    return lambda doc: prop(doc, name).__setitem__(key, value)


def _set_binding(name: str | None, value: Any) -> Mutation:
    def mutate(doc: dict[str, Any]) -> None:
        item = doc["schema"][0] if name is None else prop(doc, name)
        item.setdefault("customProperties", []).insert(0, {"property": "ssBinding", "value": value})
        # A later ssBinding entry would win; drop the original one.
        entries = [c for c in item["customProperties"] if c["property"] == "ssBinding"]
        for extra in entries[1:]:
            item["customProperties"].remove(extra)

    return mutate


CASES: dict[str, tuple[Mutation, str]] = {
    "api version": (_set(("apiVersion",), "v3.0.2"), "apiVersion must be v3.1.0"),
    "kebab id": (_set(("id",), "Sample_Reading"), "must be kebab-case"),
    "semver": (_set(("version",), "1.1"), "MAJOR.MINOR.PATCH"),
    "status": (_set(("status",), "proposed"), "status 'proposed'"),
    "purpose": (_set(("description",), {"usage": "x"}), "description.purpose is required"),
    "one schema": (lambda d: d["schema"].append(dict(d["schema"][0])), "exactly one object"),
    "no properties": (_set(("schema", 0, "properties"), []), "at least one property"),
    "snake name": (_set_prop("rssi", "name", "RSSI"), "must be snake_case"),
    "duplicate": (_set_prop("snr", "name", "rssi"), "is duplicated"),
    "python keyword": (_set_prop("rssi", "name", "class"), "is reserved"),
    "pydantic attribute": (_set_prop("rssi", "name", "model_dump"), "is reserved"),
    "shadowed type": (_set_prop("rssi", "name", "int"), "is reserved"),
    "proto word": (_set_prop("rssi", "name", "message"), "is reserved"),
    "description": (_set_prop("rssi", "description", ""), "description is required"),
    "required": (lambda d: prop(d, "rssi").pop("required"), "required must be set"),
    "kind mismatch": (_set_prop("rssi", "physicalType", "double"), "cannot carry integer"),
    "logical type": (_set_prop("rssi", "logicalType", "time"), "logicalType 'time'"),
    "items": (lambda d: prop(d, "tags").pop("items"), "needs an 'items' mapping"),
    "nested array": (
        _set_prop("tags", "items", {"logicalType": "array", "physicalType": "array"}),
        "is not a scalar kind",
    ),
    "object items with properties": (
        _set_prop(
            "tags",
            "items",
            {"logicalType": "object", "physicalType": "json", "properties": [{"name": "x"}]},
        ),
        "nested object properties",
    ),
    "nested object": (
        _set_prop("decoded_object", "properties", [{"name": "x", "logicalType": "string"}]),
        "nested object properties",
    ),
    "option": (_set_prop("dev_eui", "logicalTypeOptions", {"minItems": 1}), "minItems is not"),
    "naive timestamp": (
        _set_prop("received_at", "logicalTypeOptions", {"timezone": False}),
        "must carry a timezone",
    ),
    "unit on string": (_set_binding("dev_eui", {"unit": "m"}), "only allowed on numeric"),
    "frame": (_set_binding("position", {"frame": "ecef"}), "frame 'ecef'"),
    "time base": (_set_binding("received_at", {"timeBase": "local"}), "timeBase 'local'"),
    "topic on field": (_set_binding("rssi", {"mqttTopic": "ss/x"}), "key 'mqttTopic' is not"),
    "topic prefix": (_set_binding(None, {"mqttTopic": "site/x"}), "must start with 'ss/'"),
    "topic wildcard": (_set_binding(None, {"mqttTopic": "ss/#/x"}), "invalid level '#'"),
    "binding value": (_set_binding(None, {"modality": ""}), "must be a non-empty string"),
    "official schema": (_set(("kind",), "Contract"), "ODCS schema: kind"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_rule_violations_are_reported(case: str) -> None:
    mutate, expected = CASES[case]
    errors = _errors(mutate)
    assert any(expected in error for error in errors), errors


def test_all_findings_are_collected() -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["version"] = "x"
        properties(doc)[0]["description"] = ""

    assert len(_errors(mutate)) >= 2


def test_topic_placeholders_and_trailing_wildcard_are_valid() -> None:
    doc = _doc()
    custom(doc["schema"][0], "ssBinding")["mqttTopic"] = "ss/v1/+/{node_id}/#"
    assert parse_contract(doc, READING).binding["mqttTopic"] == "ss/v1/+/{node_id}/#"


def test_non_ascii_source_is_rejected(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "x.odcs.yaml"
    path.write_text(
        READING.read_text(encoding="utf-8").replace("Air temperature", "Air temp\u00e9rature")
    )
    with pytest.raises(ContractError, match="must be ASCII"):
        load_contract(path)


def test_invalid_yaml_is_reported(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "x.odcs.yaml"
    path.write_text("id: [unclosed\n")
    with pytest.raises(ContractError, match="invalid YAML"):
        load_contract(path)
