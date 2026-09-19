"""The contract type system: ODCS logical types, ss physical kinds, and their compatibility.

`physicalType` names the wire kind of a field. Aliases (`integer`, `bool`) normalize to one
canonical kind, so a contract may use either spelling without changing its evolution snapshot.
Per-format mappings live with each generator.
"""

# Output formats, in generation order.
FORMATS: tuple[str, ...] = ("pydantic", "jsonschema", "avro", "proto", "parquet")

# ODCS v3.1 logicalType -> the canonical physical kinds it may carry.
LOGICAL_TO_KINDS: dict[str, frozenset[str]] = {
    "string": frozenset({"string", "bytes"}),
    "integer": frozenset({"int", "long"}),
    "number": frozenset({"float", "double"}),
    "boolean": frozenset({"boolean"}),
    "timestamp": frozenset({"timestamp"}),
    "date": frozenset({"date"}),
    "object": frozenset({"json"}),
    "array": frozenset({"array"}),
}

PHYSICAL_ALIASES: dict[str, str] = {
    "integer": "int",
    "bool": "boolean",
}

# Kinds an array may hold: every scalar kind and free-form objects. Nested arrays and objects
# with declared properties are not supported.
ITEM_KINDS: frozenset[str] = frozenset(
    {"string", "bytes", "int", "long", "float", "double", "boolean", "timestamp", "date", "json"}
)

NUMERIC_KINDS: frozenset[str] = frozenset({"int", "long", "float", "double"})

# Inclusive integer ranges; the Pydantic and JSON Schema outputs enforce them so a message that
# validates in Python also fits the Protobuf and Avro integer types.
INTEGER_BOUNDS: dict[str, tuple[int, int]] = {
    "int": (-(2**31), 2**31 - 1),
    "long": (-(2**63), 2**63 - 1),
}


def canonical_kind(physical_type: str) -> str:
    """Normalize a physicalType spelling to its canonical kind."""
    return PHYSICAL_ALIASES.get(physical_type, physical_type)


def kind_compatible(logical_type: str, kind: str) -> bool:
    """Return True when the canonical kind may carry the ODCS logical type."""
    return kind in LOGICAL_TO_KINDS.get(logical_type, frozenset())
