"""Golden fixtures: canonical example messages that every consumer's CI can replay.

With `goldenDir` set in the registry, each registered contract needs `<goldenDir>/<id>/` with at
least one `*.json` message. A message must validate against the generated model and the generated
JSON Schema and round-trip: `model_dump(mode="json", exclude_unset=True)` equals the file's JSON,
so fixtures are written in canonical form (timestamps with `Z`, base64 bytes). Files named
`*.invalid.json` are counter-examples that the model and the JSON Schema must both reject.
"""

import json
import pathlib
from typing import TYPE_CHECKING, Any

import jsonschema
import pydantic

from ss_contracts.tooling.gen import jsonschema_gen, pydantic_gen
from ss_contracts.tooling.generate import source_label
from ss_contracts.tooling.odcs import ContractSpec
from ss_contracts.tooling.registry import Registry

if TYPE_CHECKING:
    from ss_contracts.base import ContractModel

INVALID_SUFFIX = ".invalid.json"


def _check_valid(model: "type[ContractModel]", validator: Any, path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    try:
        message = model.model_validate_json(text)
    except pydantic.ValidationError as exc:
        return [f"{path.name}: rejected by the model: {exc.errors()[0]['msg']}"]
    errors: list[str] = []
    payload = json.loads(text)
    schema_error = jsonschema.exceptions.best_match(validator.iter_errors(payload))
    if schema_error is not None:
        errors.append(f"{path.name}: rejected by the JSON Schema: {schema_error.message}")
    dumped = message.model_dump(mode="json", exclude_unset=True)
    if dumped != payload:
        errors.append(
            f"{path.name}: does not round-trip; the model serializes {json.dumps(dumped)}"
        )
    return errors


def _check_invalid(model: "type[ContractModel]", validator: Any, path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        model.model_validate_json(text)
        errors.append(f"{path.name}: counter-example accepted by the model")
    except pydantic.ValidationError:
        pass
    if validator.is_valid(json.loads(text)):
        errors.append(f"{path.name}: counter-example accepted by the JSON Schema")
    return errors


def check_contract(registry: Registry, spec: ContractSpec, fixture_dir: pathlib.Path) -> list[str]:
    """Findings for one contract's golden fixtures."""
    model = pydantic_gen.load_model(
        spec, pydantic_gen.render_module(spec, source_label(registry, spec))
    )
    schema = jsonschema_gen.build_schema(spec, model, registry.json_schema_id_base)
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )
    files = sorted(fixture_dir.glob("*.json"))
    valid = [path for path in files if not path.name.endswith(INVALID_SUFFIX)]
    errors: list[str] = [] if valid else ["no golden message"]
    for path in files:
        check = _check_invalid if path.name.endswith(INVALID_SUFFIX) else _check_valid
        errors.extend(check(model, validator, path))
    return [f"{spec.contract_id} [golden]: {error}" for error in errors]


def check_golden(registry: Registry, contracts: dict[str, ContractSpec]) -> list[str]:
    """Findings for every contract's golden fixtures; empty when `goldenDir` is not set."""
    golden_dir = registry.golden_dir
    if golden_dir is None:
        return []
    errors: list[str] = []
    for contract_id, spec in sorted(contracts.items()):
        errors.extend(check_contract(registry, spec, golden_dir / contract_id))
    if golden_dir.is_dir():
        for path in sorted(golden_dir.iterdir()):
            if path.is_dir() and path.name not in registry.entries:
                errors.append(f"golden fixtures {path.name}/ have no registered contract")
    return errors
