"""Generate Arrow / Parquet schemas for datasets and benchmarks.

Each contract produces a JSON descriptor (`<id>.parquet.json`: field, Arrow type, nullability,
description, binding) and an empty Parquet file (`<id>.schema.parquet`) whose footer carries the
same schema, readable with `pyarrow.parquet.read_schema`. Types: string `large_string`, bytes
`large_binary`, int `int32`, long `int64`, float `float32`, double `float64`, boolean `bool`,
timestamp `timestamp[us, tz=UTC]`, date `date32`, json `large_string` (JSON text), array
`large_list<T>`, record `struct` (its descriptor entry lists the struct `fields`).
"""

import json
import pathlib
from typing import Any

from ss_contracts.tooling.odcs import ContractSpec, FieldSpec

_ARROW_TYPES: dict[str, str] = {
    "string": "large_string",
    "bytes": "large_binary",
    "int": "int32",
    "long": "int64",
    "float": "float32",
    "double": "float64",
    "boolean": "bool",
    "timestamp": "timestamp[us, tz=UTC]",
    "date": "date32",
    "json": "large_string",
}


def arrow_type_name(fld: FieldSpec) -> str:
    value = "struct" if fld.is_record else _ARROW_TYPES[fld.value_kind]
    return f"large_list<{value}>" if fld.kind == "array" else value


def _descriptor_entry(fld: FieldSpec) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": fld.name,
        "arrow_type": arrow_type_name(fld),
        "nullable": not fld.required,
        "description": fld.description,
    }
    if fld.binding:
        entry["ss_binding"] = dict(fld.binding)
    if fld.is_record:
        entry["fields"] = [_descriptor_entry(sub) for sub in fld.record_fields]
    return entry


def build_descriptor(spec: ContractSpec) -> dict[str, Any]:
    return {
        "contract_id": spec.contract_id,
        "version": spec.version,
        "entity": spec.name,
        "fields": [_descriptor_entry(fld) for fld in spec.fields],
    }


def render(spec: ContractSpec) -> str:
    return json.dumps(build_descriptor(spec), indent=2) + "\n"


def _arrow_scalar(kind: str) -> Any:
    import pyarrow as pa

    factories: dict[str, Any] = {
        "string": pa.large_string,
        "bytes": pa.large_binary,
        "int": pa.int32,
        "long": pa.int64,
        "float": pa.float32,
        "double": pa.float64,
        "boolean": pa.bool_,
        "timestamp": lambda: pa.timestamp("us", tz="UTC"),
        "date": pa.date32,
        "json": pa.large_string,
    }
    return factories[kind]()


def _arrow_field(fld: FieldSpec) -> Any:
    import pyarrow as pa

    if fld.is_record:
        value_type = pa.struct([_arrow_field(sub) for sub in fld.record_fields])
    else:
        value_type = _arrow_scalar(fld.value_kind)
    arrow_type = pa.large_list(value_type) if fld.kind == "array" else value_type
    metadata = {"description": fld.description}
    if fld.binding:
        metadata["ss_binding"] = json.dumps(dict(fld.binding), sort_keys=True)
    return pa.field(fld.name, arrow_type, nullable=not fld.required, metadata=metadata)


def arrow_schema(spec: ContractSpec) -> Any:
    """The contract as a `pyarrow.Schema` with field descriptions in the field metadata."""
    import pyarrow as pa

    fields = [_arrow_field(fld) for fld in spec.fields]
    contract = {"id": spec.contract_id, "version": spec.version}
    return pa.schema(fields, metadata={"ss_contract": json.dumps(contract, sort_keys=True)})


def write_schema_file(spec: ContractSpec, path: pathlib.Path) -> None:
    """Write an empty Parquet file whose footer carries the contract schema."""
    import pyarrow.parquet as pq

    schema = arrow_schema(spec)
    pq.write_table(schema.empty_table(), path)
