"""Generation readiness: every hint a format needs is present and well-formed.

| Format | `schemaGeneration` (message) | `fieldGeneration` (field) |
| --- | --- | --- |
| `pydantic`, `jsonschema` | `pydantic.className` | -- |
| `avro` | `avro.namespace`, `avro.recordName` | -- |
| `proto` | `proto.package`, `proto.messageName`; optional `goPackage`, `reserved`, `reservedNames` | `proto.fieldNumber` |
| `parquet` | -- | -- |
"""

import re
from collections.abc import Callable, Mapping
from typing import Any

from ss_contracts.tooling.odcs import ContractSpec
from ss_contracts.tooling.types import FORMATS

__all__ = ["FORMATS", "generation_errors"]

_TYPE_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_AVRO_NAMESPACE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_PROTO_PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
PROTO_MAX_FIELD_NUMBER = 536_870_911
PROTO_IMPLEMENTATION_RESERVED = range(19_000, 20_000)


def _require(hints: Mapping[str, Any], key: str, pattern: re.Pattern[str], fmt: str) -> list[str]:
    value = hints.get(key)
    if not isinstance(value, str) or not pattern.match(value):
        return [f"schemaGeneration.{fmt}.{key} must match {pattern.pattern}"]
    return []


def _pydantic_errors(spec: ContractSpec) -> list[str]:
    return _require(spec.generation_hints("pydantic"), "className", _TYPE_NAME_RE, "pydantic")


def _avro_errors(spec: ContractSpec) -> list[str]:
    hints = spec.generation_hints("avro")
    return _require(hints, "namespace", _AVRO_NAMESPACE_RE, "avro") + _require(
        hints, "recordName", _TYPE_NAME_RE, "avro"
    )


def _int_list(value: Any) -> list[int] | None:
    if value is None:
        return []
    if isinstance(value, list) and all(
        isinstance(v, int) and not isinstance(v, bool) for v in value
    ):
        return value
    return None


def _proto_message_errors(hints: Mapping[str, Any]) -> list[str]:
    errors = _require(hints, "package", _PROTO_PACKAGE_RE, "proto")
    errors += _require(hints, "messageName", _TYPE_NAME_RE, "proto")
    if "goPackage" in hints and not isinstance(hints["goPackage"], str):
        errors.append("schemaGeneration.proto.goPackage must be a string")
    if _int_list(hints.get("reserved")) is None:
        errors.append("schemaGeneration.proto.reserved must be a list of field numbers")
    names = hints.get("reservedNames", [])
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        errors.append("schemaGeneration.proto.reservedNames must be a list of names")
    return errors


def _field_number_error(number: Any, used: set[int], reserved: list[int]) -> str | None:
    if not isinstance(number, int) or isinstance(number, bool):
        return "fieldGeneration.proto.fieldNumber is missing"
    if not 1 <= number <= PROTO_MAX_FIELD_NUMBER or number in PROTO_IMPLEMENTATION_RESERVED:
        return f"fieldGeneration.proto.fieldNumber {number} is outside the usable range"
    if number in used:
        return f"fieldGeneration.proto.fieldNumber {number} is used twice"
    if number in reserved:
        return f"fieldGeneration.proto.fieldNumber {number} is reserved"
    used.add(number)
    return None


def _proto_errors(spec: ContractSpec) -> list[str]:
    hints = spec.generation_hints("proto")
    errors = _proto_message_errors(hints)
    reserved = _int_list(hints.get("reserved")) or []
    reserved_names = hints.get("reservedNames") or []
    used: set[int] = set()
    for fld in spec.fields:
        number = fld.generation.get("proto", {}).get("fieldNumber")
        error = _field_number_error(number, used, reserved)
        if error:
            errors.append(f"field '{fld.name}': {error}")
        if fld.name in reserved_names:
            errors.append(f"field '{fld.name}': name is listed in proto reservedNames")
    return errors


_CHECKS: dict[str, Callable[[ContractSpec], list[str]]] = {
    "pydantic": _pydantic_errors,
    "jsonschema": _pydantic_errors,
    "avro": _avro_errors,
    "proto": _proto_errors,
    "parquet": lambda spec: [],
}


def generation_errors(spec: ContractSpec, fmt: str) -> list[str]:
    """Findings that would stop `fmt` from generating this contract."""
    return [f"{spec.contract_id} [{fmt}]: {error}" for error in _CHECKS[fmt](spec)]
