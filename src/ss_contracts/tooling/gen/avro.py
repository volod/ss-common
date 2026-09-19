"""Generate Avro record schemas (`.avsc`) for datasets and benchmarks.

Types: timestamp `long` / `timestamp-micros`, date `int` / `date`, json `string` (JSON text),
array `array`; an optional field is a `["null", T]` union with a `null` default. Bindings are
kept as a field attribute `ssBinding`, which Avro's parsing canonical form ignores.
"""

import copy
import json
from typing import Any

import fastavro

from ss_contracts.tooling.odcs import ContractSpec, FieldSpec

_AVRO_TYPES: dict[str, Any] = {
    "string": "string",
    "bytes": "bytes",
    "int": "int",
    "long": "long",
    "float": "float",
    "double": "double",
    "boolean": "boolean",
    "timestamp": {"type": "long", "logicalType": "timestamp-micros"},
    "date": {"type": "int", "logicalType": "date"},
    "json": "string",
}


def _base_type(fld: FieldSpec) -> Any:
    if fld.kind == "array":
        return {"type": "array", "items": copy.deepcopy(_AVRO_TYPES[str(fld.item_kind)])}
    return copy.deepcopy(_AVRO_TYPES[fld.kind])


def _field(fld: FieldSpec) -> dict[str, Any]:
    doc = fld.description + (" (JSON-encoded object)" if fld.kind == "json" else "")
    entry: dict[str, Any] = {"name": fld.name, "doc": doc}
    base = _base_type(fld)
    if fld.required:
        entry["type"] = base
    else:
        entry["type"] = ["null", base]
        entry["default"] = None
    if fld.binding:
        entry["ssBinding"] = dict(fld.binding)
    return entry


def build_schema(spec: ContractSpec) -> dict[str, Any]:
    hints = spec.generation_hints("avro")
    return {
        "type": "record",
        "name": hints["recordName"],
        "namespace": hints["namespace"],
        "doc": spec.purpose,
        "fields": [_field(fld) for fld in spec.fields],
    }


def render(spec: ContractSpec) -> str:
    schema = build_schema(spec)
    fastavro.parse_schema(copy.deepcopy(schema))
    return json.dumps(schema, indent=2) + "\n"
