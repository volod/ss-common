"""Generate JSON Schema (draft 2020-12) from the generated Pydantic model.

Deriving the schema from the model, rather than from ODCS directly, guarantees that the Python
services and every JSON Schema consumer accept exactly the same messages.
"""

import json
from typing import TYPE_CHECKING, Any

from ss_contracts.tooling.odcs import ContractSpec

if TYPE_CHECKING:
    from ss_contracts.base import ContractModel

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def schema_id(id_base: str, spec: ContractSpec) -> str:
    return f"{id_base}:{spec.contract_id}:{spec.version}"


def build_schema(spec: ContractSpec, model: "type[ContractModel]", id_base: str) -> dict[str, Any]:
    body = model.model_json_schema()
    schema: dict[str, Any] = {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": schema_id(id_base, spec),
        **body,
        # The class docstring is wrapped for line length; the schema carries the purpose as is.
        "description": spec.purpose,
        "x-ss-contract": {"id": spec.contract_id, "version": spec.version},
    }
    if spec.binding:
        schema["x-ss-binding"] = dict(spec.binding)
    return schema


def render(spec: ContractSpec, model: "type[ContractModel]", id_base: str) -> str:
    return json.dumps(build_schema(spec, model, id_base), indent=2, sort_keys=True) + "\n"
