"""Load ODCS v3.1 message contracts and normalize them for the generators.

`load_contract` reads a YAML source (which must be ASCII, so every generated artifact is too),
checks it against the official ODCS JSON Schema and the [authoring rules](rules.py), and returns a
`ContractSpec`; any finding raises `ContractError` listing all of them.
"""

import pathlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

from ss_contracts.tooling.binding import BINDING_PROPERTY, normalize_binding
from ss_contracts.tooling.rules import (
    find_custom_property,
    official_schema_errors,
    record_name,
    schema_object,
    ss_rule_errors,
)
from ss_contracts.tooling.types import RECORD_KIND, canonical_kind

SCHEMA_GEN_PROPERTY = "schemaGeneration"
FIELD_GEN_PROPERTY = "fieldGeneration"


class ContractError(ValueError):
    """A contract document failed validation; `errors` lists every finding."""

    def __init__(self, source: pathlib.Path, errors: list[str]) -> None:
        self.source = source
        self.errors = errors
        super().__init__(f"{source}: " + "; ".join(errors))


@dataclass(frozen=True)
class FieldSpec:
    """One message field, normalized from an ODCS property."""

    name: str
    logical_type: str
    kind: str
    required: bool
    description: str
    options: Mapping[str, Any] = field(default_factory=dict)
    item_kind: str | None = None
    binding: Mapping[str, str] = field(default_factory=dict)
    generation: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    record_name: str | None = None
    record_fields: tuple["FieldSpec", ...] = ()
    # What one record is: `items.description` for an array of records, else the field's.
    record_description: str = ""

    @property
    def is_record(self) -> bool:
        """The field is a record or an array of records."""
        return RECORD_KIND in (self.kind, self.item_kind)

    @property
    def value_kind(self) -> str:
        """The kind of one value: the item kind of an array, else the field kind."""
        return str(self.item_kind) if self.kind == "array" else self.kind


def iter_records(fields: tuple[FieldSpec, ...]) -> Iterator[FieldSpec]:
    """The record fields of a message, in field order (records nest one level)."""
    return (fld for fld in fields if fld.is_record)


@dataclass(frozen=True)
class ContractSpec:
    """One message contract, normalized from an ODCS document."""

    contract_id: str
    version: str
    status: str
    name: str
    purpose: str
    fields: tuple[FieldSpec, ...]
    binding: Mapping[str, str]
    generation: Mapping[str, Mapping[str, Any]]
    source: pathlib.Path
    doc: Mapping[str, Any]

    def generation_hints(self, fmt: str) -> Mapping[str, Any]:
        """Message-level `schemaGeneration` hints for one output format."""
        hints = self.generation.get(fmt)
        return hints if isinstance(hints, Mapping) else {}


def _generation(custom_properties: Any, name: str) -> dict[str, Mapping[str, Any]]:
    value = find_custom_property(custom_properties, name)
    if not isinstance(value, Mapping):
        return {}
    return {str(fmt): hints for fmt, hints in value.items() if isinstance(hints, Mapping)}


def _record_parts(prop: Mapping[str, Any], kind: str, items: Any) -> dict[str, Any]:
    body = items if kind == "array" and isinstance(items, Mapping) else prop
    if canonical_kind(str(body.get("physicalType", ""))) != RECORD_KIND:
        return {}
    description = body.get("description") or prop["description"]
    return {
        # `fieldGeneration.recordName` names the record type in every output format.
        "record_name": str(record_name(prop)),
        "record_fields": tuple(_field_spec(sub) for sub in _iter_properties(body)),
        "record_description": " ".join(str(description).split()),
    }


def _field_spec(prop: Mapping[str, Any]) -> FieldSpec:
    custom = prop.get("customProperties")
    items = prop.get("items")
    item_kind = None
    if isinstance(items, Mapping):
        item_kind = canonical_kind(str(items.get("physicalType", "")))
    options = prop.get("logicalTypeOptions")
    kind = canonical_kind(str(prop["physicalType"]))
    return FieldSpec(
        name=str(prop["name"]),
        logical_type=str(prop["logicalType"]),
        kind=kind,
        required=bool(prop["required"]),
        description=" ".join(str(prop["description"]).split()),
        options=dict(options) if isinstance(options, Mapping) else {},
        item_kind=item_kind,
        binding=normalize_binding(find_custom_property(custom, BINDING_PROPERTY)),
        generation=_generation(custom, FIELD_GEN_PROPERTY),
        **_record_parts(prop, kind, items),
    )


def _iter_properties(schema_obj: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    for prop in schema_obj.get("properties", []):
        if isinstance(prop, Mapping):
            yield prop


def parse_contract(doc: Any, source: pathlib.Path) -> ContractSpec:
    """Validate one ODCS document and normalize it; raise ContractError on any finding."""
    if not isinstance(doc, Mapping):
        raise ContractError(source, ["document is not a mapping"])
    errors = official_schema_errors(doc) + ss_rule_errors(doc)
    if errors:
        raise ContractError(source, errors)
    schema_obj = schema_object(doc)
    assert schema_obj is not None  # guaranteed by ss_rule_errors
    custom = schema_obj.get("customProperties")
    return ContractSpec(
        contract_id=str(doc["id"]),
        version=str(doc["version"]),
        status=str(doc["status"]),
        name=str(schema_obj["name"]),
        purpose=" ".join(str(doc["description"]["purpose"]).split()),
        fields=tuple(_field_spec(prop) for prop in _iter_properties(schema_obj)),
        binding=normalize_binding(find_custom_property(custom, BINDING_PROPERTY)),
        generation=_generation(custom, SCHEMA_GEN_PROPERTY),
        source=source,
        doc=doc,
    )


def load_contract(path: pathlib.Path) -> ContractSpec:
    """Read, validate, and normalize one ODCS YAML contract."""
    text = path.read_text(encoding="utf-8")
    if not text.isascii():
        raise ContractError(path, ["contract source must be ASCII"])
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ContractError(path, [f"invalid YAML: {exc}"]) from exc
    return parse_contract(doc, path)
