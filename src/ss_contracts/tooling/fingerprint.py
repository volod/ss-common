"""Structural fingerprints recorded in evolution snapshots.

`avroParsingFingerprint` is SHA-256 over the Avro Parsing Canonical Form of the generated schema.
The canonical form drops docs, defaults, and custom attributes, so the fingerprint moves only when
the serialized structure (names, types, field order) moves.
"""

import copy
import hashlib
from typing import Any

import fastavro

from ss_contracts.tooling.gen import avro
from ss_contracts.tooling.gen.checker import generation_errors
from ss_contracts.tooling.odcs import ContractSpec


def avro_parsing_fingerprint(schema: dict[str, Any]) -> str:
    canonical: str = fastavro.schema.to_parsing_canonical_form(copy.deepcopy(schema))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def contract_fingerprints(spec: ContractSpec) -> dict[str, str]:
    """Fingerprints available for a contract; empty when its Avro hints are incomplete."""
    if generation_errors(spec, "avro"):
        return {}
    return {"avroParsingFingerprint": avro_parsing_fingerprint(avro.build_schema(spec))}
