"""The contract registry: `contracts/registry.yaml` lists every contract and the output paths.

```yaml
registryVersion: 1
jsonSchemaIdBase: urn:ss:contracts        # JSON Schema $id prefix
modelsDir: ../src/ss_contracts/models     # committed Pydantic models (drift-gated)
generatedDir: generated                   # JSON Schema, Protobuf, Avro, Parquet (gitignored)
goldenDir: ../tests/fixtures/contracts/golden  # optional: <goldenDir>/<contract-id>/*.json
contracts:
  sensor-reading:
    odcs: odcs/sensor-reading.odcs.yaml
    owner: ss-sens                        # the producing service
```

Every relative path resolves against the directory holding `registry.yaml`. Contract paths must
stay inside it; output paths may point elsewhere in the project.
"""

import os
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

from ss_contracts.tooling.odcs import ContractError, ContractSpec, load_contract
from ss_contracts.tooling.rules import CONTRACT_ID_RE
from ss_kit.quality.project_root import discover_project_root

REGISTRY_FILENAME = "registry.yaml"
REGISTRY_VERSION = 1
ROOT_ENV = "SS_CONTRACTS_ROOT"
EVOLUTION_DIRNAME = "evolution"
ODCS_DIRNAME = "odcs"
ODCS_SUFFIX = ".odcs.yaml"


class RegistryError(ValueError):
    """The registry document itself is unusable."""


@dataclass(frozen=True)
class RegistryEntry:
    contract_id: str
    odcs: pathlib.Path
    owner: str


@dataclass(frozen=True)
class Registry:
    root: pathlib.Path
    models_dir: pathlib.Path
    generated_dir: pathlib.Path
    golden_dir: pathlib.Path | None
    json_schema_id_base: str
    entries: Mapping[str, RegistryEntry] = field(default_factory=dict)

    @property
    def evolution_dir(self) -> pathlib.Path:
        return self.root / EVOLUTION_DIRNAME

    def contains(self, path: pathlib.Path) -> bool:
        return path.resolve().is_relative_to(self.root.resolve())

    def consistency_errors(self) -> list[str]:
        """Registry-level findings: missing files, escapes, and unregistered contracts."""
        errors: list[str] = []
        registered: set[pathlib.Path] = set()
        for entry in self.entries.values():
            path = entry.odcs.resolve()
            registered.add(path)
            if not self.contains(path):
                errors.append(f"{entry.contract_id}: odcs path leaves the contracts root")
            elif not path.is_file():
                errors.append(f"{entry.contract_id}: odcs file {entry.odcs} does not exist")
        odcs_dir = self.root / ODCS_DIRNAME
        for path in sorted(odcs_dir.rglob(f"*{ODCS_SUFFIX}")) if odcs_dir.is_dir() else []:
            if path.resolve() not in registered:
                errors.append(f"{path.relative_to(self.root)} is not registered")
        return errors

    def load_contracts(self) -> tuple[dict[str, ContractSpec], list[str]]:
        """Load every registered contract; return the valid ones and every finding."""
        contracts: dict[str, ContractSpec] = {}
        errors = self.consistency_errors()
        for contract_id, entry in self.entries.items():
            if not self.contains(entry.odcs) or not entry.odcs.is_file():
                continue
            try:
                spec = load_contract(entry.odcs)
            except ContractError as exc:
                errors.extend(f"{contract_id}: {error}" for error in exc.errors)
                continue
            if spec.contract_id != contract_id:
                errors.append(f"{contract_id}: ODCS id '{spec.contract_id}' differs from its key")
                continue
            contracts[contract_id] = spec
        return contracts, errors


def default_root() -> pathlib.Path:
    """`$SS_CONTRACTS_ROOT`, else `contracts/` under the project root."""
    configured = os.environ.get(ROOT_ENV)
    project_root = discover_project_root()
    if configured:
        path = pathlib.Path(configured)
        return path if path.is_absolute() else project_root / path
    return project_root / "contracts"


def _required_str(doc: Mapping[str, Any], key: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{REGISTRY_FILENAME}: '{key}' must be a non-empty string")
    return value


def _entry(root: pathlib.Path, contract_id: Any, spec: Any) -> RegistryEntry:
    if not isinstance(contract_id, str) or not CONTRACT_ID_RE.match(contract_id):
        raise RegistryError(f"{REGISTRY_FILENAME}: contract id '{contract_id}' must be kebab-case")
    if not isinstance(spec, Mapping):
        raise RegistryError(f"{REGISTRY_FILENAME}: entry '{contract_id}' must be a mapping")
    odcs = _required_str(spec, "odcs")
    if not odcs.endswith(ODCS_SUFFIX) or pathlib.PurePath(odcs).is_absolute():
        raise RegistryError(f"{contract_id}: odcs must be a relative *{ODCS_SUFFIX} path")
    return RegistryEntry(contract_id, root / odcs, _required_str(spec, "owner"))


def load_registry(root: pathlib.Path | None = None) -> Registry:
    """Parse `<root>/registry.yaml`; raise RegistryError when it is unusable."""
    root = (root or default_root()).resolve()
    path = root / REGISTRY_FILENAME
    if not path.is_file():
        raise RegistryError(f"{path} does not exist")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping) or doc.get("registryVersion") != REGISTRY_VERSION:
        raise RegistryError(f"{path}: registryVersion must be {REGISTRY_VERSION}")
    contracts = doc.get("contracts")
    contracts = {} if contracts is None else contracts
    if not isinstance(contracts, Mapping):
        raise RegistryError(f"{path}: 'contracts' must be a mapping")
    golden = doc.get("goldenDir")
    return Registry(
        root=root,
        models_dir=(root / _required_str(doc, "modelsDir")).resolve(),
        generated_dir=(root / _required_str(doc, "generatedDir")).resolve(),
        golden_dir=(root / golden).resolve() if isinstance(golden, str) and golden else None,
        json_schema_id_base=_required_str(doc, "jsonSchemaIdBase"),
        entries={cid: _entry(root, cid, spec) for cid, spec in contracts.items()},
    )
