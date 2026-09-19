"""The ss authoring rules for ODCS v3.1 message contracts.

A contract is valid when it passes the vendored official ODCS JSON Schema and these rules:

- `apiVersion` is `v3.1.0`; `id` is kebab-case; `version` is `MAJOR.MINOR.PATCH`; `status` is one
  of `draft`, `active`, `deprecated`, `retired`; `description.purpose` is set;
- `schema` holds exactly one object with at least one property (one contract, one message);
- every property has a snake-case `name` that is unique and is not a Python keyword, a proto3
  reserved word, a Pydantic model attribute, or a type name the generated module uses
  (`GENERATED_NAMES`); a `description`; an explicit `required`; a
  `logicalType` and a `physicalType` from the [type system](types.py); arrays declare scalar
  `items`; free-form objects (`object` / `json`) declare no nested `properties`;
- `logicalTypeOptions` use only the keys the generators enforce (`SUPPORTED_OPTIONS`);
- `ssBinding` values follow the [binding rules](binding.py);
- the YAML source is ASCII, so every generated artifact is too.

Generation hints (`schemaGeneration`, `fieldGeneration`) are checked per output format by
`gen.checker`, and the ASCII rule by `odcs.load_contract`.
"""

import functools
import json
import keyword
import re
from collections.abc import Mapping
from importlib import resources
from typing import Any

import jsonschema

from ss_contracts.tooling.binding import (
    BINDING_PROPERTY,
    FIELD_KEYS,
    MESSAGE_KEYS,
    binding_errors,
)
from ss_contracts.tooling.types import (
    ITEM_KINDS,
    LOGICAL_TO_KINDS,
    NUMERIC_KINDS,
    canonical_kind,
    kind_compatible,
)

API_VERSION = "v3.1.0"
ODCS_SCHEMA_RESOURCE = "odcs-json-schema-v3.1.0.json"
STATUSES: frozenset[str] = frozenset({"draft", "active", "deprecated", "retired"})

CONTRACT_ID_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Names the generated Python module binds at class scope or uses in annotations; a field with one
# of these names would shadow the type for every later field.
GENERATED_NAMES: frozenset[str] = frozenset(
    {"str", "int", "float", "bool", "bytes", "list", "dict", "datetime"}
)

SUPPORTED_OPTIONS: dict[str, frozenset[str]] = {
    "string": frozenset({"minLength", "maxLength", "pattern", "format"}),
    "integer": frozenset(
        {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "format"}
    ),
    "number": frozenset(
        {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
    ),
    "array": frozenset({"minItems", "maxItems"}),
    "timestamp": frozenset({"timezone"}),
}

PROTO3_RESERVED_WORDS: frozenset[str] = frozenset(
    {
        "syntax", "import", "package", "option", "message", "enum", "service", "rpc",
        "returns", "stream", "oneof", "map", "extensions", "reserved", "to", "max",
        "repeated", "optional", "required", "weak", "public",
    }
)  # fmt: skip


def find_custom_property(custom_properties: Any, name: str) -> Any:
    """Return the value of a named entry in an ODCS `customProperties` list, or None."""
    if not isinstance(custom_properties, list):
        return None
    for item in custom_properties:
        if isinstance(item, Mapping) and item.get("property") == name:
            return item.get("value")
    return None


@functools.cache
def _odcs_validator() -> jsonschema.Draft201909Validator:
    text = resources.files("ss_contracts.tooling").joinpath("schemas", ODCS_SCHEMA_RESOURCE)
    schema = json.loads(text.read_text(encoding="utf-8"))
    return jsonschema.Draft201909Validator(schema)


def official_schema_errors(doc: Any) -> list[str]:
    """Findings from the official ODCS v3.1.0 JSON Schema."""
    findings = sorted(_odcs_validator().iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [
        f"ODCS schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in findings
    ]


@functools.cache
def _reserved_field_names() -> frozenset[str]:
    from pydantic import BaseModel

    return (
        frozenset(keyword.kwlist)
        | PROTO3_RESERVED_WORDS
        | GENERATED_NAMES
        | frozenset(dir(BaseModel))
    )


def _header_errors(doc: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if doc.get("apiVersion") != API_VERSION:
        errors.append(f"apiVersion must be {API_VERSION}")
    if not CONTRACT_ID_RE.match(str(doc.get("id", ""))):
        errors.append(f"id '{doc.get('id')}' must be kebab-case")
    if not VERSION_RE.match(str(doc.get("version", ""))):
        errors.append(f"version '{doc.get('version')}' must be MAJOR.MINOR.PATCH")
    if doc.get("status") not in STATUSES:
        errors.append(f"status '{doc.get('status')}' must be one of {sorted(STATUSES)}")
    description = doc.get("description")
    if not isinstance(description, Mapping) or not description.get("purpose"):
        errors.append("description.purpose is required")
    return errors


def schema_object(doc: Mapping[str, Any]) -> Mapping[str, Any] | None:
    schema = doc.get("schema")
    if isinstance(schema, list) and len(schema) == 1 and isinstance(schema[0], Mapping):
        return schema[0]
    return None


def _items_errors(prop: Mapping[str, Any]) -> list[str]:
    items = prop.get("items")
    if not isinstance(items, Mapping):
        return ["array needs an 'items' mapping"]
    kind = canonical_kind(str(items.get("physicalType", "")))
    if kind not in ITEM_KINDS:
        return [f"items.physicalType '{items.get('physicalType')}' is not a scalar kind or json"]
    if not kind_compatible(str(items.get("logicalType", "")), kind):
        return [f"items.logicalType '{items.get('logicalType')}' cannot carry '{kind}'"]
    if kind == "json" and items.get("properties"):
        return ["nested object properties are not supported; use a free-form object"]
    return []


def _type_errors(prop: Mapping[str, Any]) -> list[str]:
    logical = str(prop.get("logicalType", ""))
    kind = canonical_kind(str(prop.get("physicalType", "")))
    if logical not in LOGICAL_TO_KINDS:
        return [f"logicalType '{logical}' is not supported {sorted(LOGICAL_TO_KINDS)}"]
    if not kind_compatible(logical, kind):
        allowed = sorted(LOGICAL_TO_KINDS[logical])
        return [f"physicalType '{prop.get('physicalType')}' cannot carry {logical} {allowed}"]
    if kind == "array":
        return _items_errors(prop)
    if kind == "json" and prop.get("properties"):
        return ["nested object properties are not supported; use a free-form object"]
    return []


def _options_errors(prop: Mapping[str, Any]) -> list[str]:
    options = prop.get("logicalTypeOptions")
    if not isinstance(options, Mapping):
        return []
    supported = SUPPORTED_OPTIONS.get(str(prop.get("logicalType")), frozenset())
    errors = [
        f"logicalTypeOptions.{key} is not supported" for key in options if key not in supported
    ]
    if options.get("timezone") is False:
        errors.append("timestamps must carry a timezone (logicalTypeOptions.timezone: true)")
    return errors


def _name_errors(name: Any, seen: set[str]) -> list[str]:
    if not isinstance(name, str) or not FIELD_NAME_RE.match(name):
        return [f"property name '{name}' must be snake_case"]
    if name in seen:
        return [f"property name '{name}' is duplicated"]
    seen.add(name)
    if name in _reserved_field_names():
        return [f"property name '{name}' is reserved in Python, proto3, or Pydantic"]
    return []


def _unit_errors(prop: Mapping[str, Any], binding: Any) -> list[str]:
    if not isinstance(binding, Mapping) or "unit" not in binding:
        return []
    kind = canonical_kind(str(prop.get("physicalType", "")))
    items = prop.get("items")
    if kind == "array" and isinstance(items, Mapping):
        kind = canonical_kind(str(items.get("physicalType", "")))
    return [] if kind in NUMERIC_KINDS else ["ssBinding.unit is only allowed on numeric fields"]


def _property_errors(prop: Any, seen: set[str]) -> list[str]:
    if not isinstance(prop, Mapping):
        return ["property must be a mapping"]
    errors = _name_errors(prop.get("name"), seen)
    if not prop.get("description"):
        errors.append("description is required")
    if not isinstance(prop.get("required"), bool):
        errors.append("required must be set explicitly to true or false")
    errors.extend(_type_errors(prop))
    errors.extend(_options_errors(prop))
    binding = find_custom_property(prop.get("customProperties"), BINDING_PROPERTY)
    errors.extend(binding_errors(binding, FIELD_KEYS))
    errors.extend(_unit_errors(prop, binding))
    return [f"property '{prop.get('name')}': {error}" for error in errors]


def ss_rule_errors(doc: Mapping[str, Any]) -> list[str]:
    """Findings from the ss authoring rules (see the module docstring)."""
    errors = _header_errors(doc)
    schema_obj = schema_object(doc)
    if schema_obj is None:
        return [*errors, "schema must hold exactly one object"]
    binding = find_custom_property(schema_obj.get("customProperties"), BINDING_PROPERTY)
    errors.extend(f"schema[0]: {error}" for error in binding_errors(binding, MESSAGE_KEYS))
    properties = schema_obj.get("properties")
    if not isinstance(properties, list) or not properties:
        return [*errors, "schema[0] needs at least one property"]
    seen: set[str] = set()
    for prop in properties:
        errors.extend(_property_errors(prop, seen))
    return errors
