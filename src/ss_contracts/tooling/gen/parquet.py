"""Generate Arrow / Parquet schemas for datasets and benchmarks.

Each contract produces a JSON descriptor (`<id>.parquet.json`: field, Arrow type, nullability,
description, binding) and an empty Parquet file (`<id>.schema.parquet`) whose footer carries the
same schema, readable with `pyarrow.parquet.read_schema`. Types: string `large_string`, bytes
`large_binary`, int `int32`, long `int64`, float `float32`, double `float64`, boolean `bool`,
timestamp `timestamp[us, tz=UTC]`, date `date32`, json `large_string` (JSON text), array
`large_list<T>`.
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
    if fld.kind == "array":
        return f"large_list<{_ARROW_TYPES[str(fld.item_kind)]}>"
    return _ARROW_TYPES[fld.kind]


def build_descriptor(spec: ContractSpec) -> dict[str, Any]:
    fields = []
    for fld in spec.fields:
        entry: dict[str, Any] = {
            "name": fld.name,
            "arrow_type": arrow_type_name(fld),
            "nullable": not fld.required,
            "description": fld.description,
        }
        if fld.binding:
            entry["ss_binding"] = dict(fld.binding)
        fields.append(entry)
    return {
        "contract_id": spec.contract_id,
        "version": spec.version,
        "entity": spec.name,
        "fields": fields,
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


def arrow_schema(spec: ContractSpec) -> Any:
    """The contract as a `pyarrow.Schema` with field descriptions in the field metadata."""
    import pyarrow as pa

    fields = []
    for fld in spec.fields:
        if fld.kind == "array":
            arrow_type = pa.large_list(_arrow_scalar(str(fld.item_kind)))
        else:
            arrow_type = _arrow_scalar(fld.kind)
        metadata = {"description": fld.description}
        if fld.binding:
            metadata["ss_binding"] = json.dumps(dict(fld.binding), sort_keys=True)
        fields.append(pa.field(fld.name, arrow_type, nullable=not fld.required, metadata=metadata))
    contract = {"id": spec.contract_id, "version": spec.version}
    return pa.schema(fields, metadata={"ss_contract": json.dumps(contract, sort_keys=True)})


def write_schema_file(spec: ContractSpec, path: pathlib.Path) -> None:
    """Write an empty Parquet file whose footer carries the contract schema."""
    import pyarrow.parquet as pq

    schema = arrow_schema(spec)
    pq.write_table(schema.empty_table(), path)
