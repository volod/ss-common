"""Schema evolution: reviewed baselines with history, checked against the evolution policy.

Every registered contract has a committed baseline `contracts/evolution/<id>.json` holding its
latest reviewed snapshot and the full `history` of reviewed snapshots. The current contract is
classified against the latest snapshot and every adjacent history pair is re-checked with the
[evolution policy](evolution_policy.py), so a consumer several versions behind still has a
reviewed upgrade path. A contract without a baseline, a baseline without history, and a baseline
without a contract fail. `evolution-freeze` records the current snapshots after review; it
refuses a snapshot the policy rejects, so history only holds reviewed, policy-conforming steps.
"""

import itertools
import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ss_contracts.tooling.evolution_policy import (
    CHANGE_BACKWARD,
    CHANGE_BREAKING,
    CHANGE_IDENTICAL,
    ChangeReport,
    classify_change,
    proto_number_errors,
    schema_snapshot,
    version_policy_errors,
)
from ss_contracts.tooling.odcs import ContractSpec
from ss_contracts.tooling.registry import Registry

__all__ = [
    "CHANGE_BACKWARD",
    "CHANGE_BREAKING",
    "CHANGE_IDENTICAL",
    "ContractEvolution",
    "EvolutionReport",
    "baseline_path",
    "check_evolution",
    "classify_change",
    "freeze_baselines",
    "load_history",
]

_COMPARABLE_KEYS = ("contractId", "version", "binding", "fields", "fingerprints")


@dataclass
class ContractEvolution:
    contract_id: str
    baseline_version: str | None
    current_version: str
    change_class: str
    details: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    history_versions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class EvolutionReport:
    contracts: list[ContractEvolution] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and all(c.ok for c in self.contracts)


def baseline_path(registry: Registry, contract_id: str) -> pathlib.Path:
    return registry.evolution_dir / f"{contract_id}.json"


def load_history(registry: Registry, contract_id: str) -> list[dict[str, Any]] | None:
    """Reviewed snapshots of a contract; None when it has no baseline file."""
    path = baseline_path(registry, contract_id)
    if not path.is_file():
        return None
    history = json.loads(path.read_text(encoding="utf-8")).get("history")
    return [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []


def _step_errors(
    contract_id: str, older: Mapping[str, Any], newer: Mapping[str, Any]
) -> tuple[ChangeReport, list[str]]:
    change = classify_change(older, newer)
    errors = version_policy_errors(
        contract_id, str(older.get("version")), str(newer.get("version")), change
    )
    return change, errors


def _history_errors(contract_id: str, history: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for older, newer in itertools.pairwise(history):
        errors += [f"history: {error}" for error in _step_errors(contract_id, older, newer)[1]]
    return errors


def evaluate(registry: Registry, spec: ContractSpec) -> ContractEvolution:
    """Check one contract against its reviewed history."""
    current = schema_snapshot(spec)
    history = load_history(registry, spec.contract_id)
    result = ContractEvolution(spec.contract_id, None, spec.version, CHANGE_BREAKING)
    if not history:
        state = "no committed baseline" if history is None else "a baseline without history"
        result.errors.append(
            f"{spec.contract_id}: {state}; review it and run 'make evolution-freeze'"
        )
        return result
    latest = history[-1]
    change, errors = _step_errors(spec.contract_id, latest, current)
    result.baseline_version = str(latest.get("version"))
    result.change_class, result.details = change.change_class, change.details
    result.history_versions = [str(item.get("version")) for item in history]
    result.errors = errors + _history_errors(spec.contract_id, history)
    result.errors += proto_number_errors(spec.contract_id, [*history, current])
    return result


def _stale_baselines(registry: Registry, contract_ids: set[str]) -> list[pathlib.Path]:
    if not registry.evolution_dir.is_dir():
        return []
    return [p for p in sorted(registry.evolution_dir.glob("*.json")) if p.stem not in contract_ids]


def check_evolution(registry: Registry) -> EvolutionReport:
    """Check every registered contract against its committed baseline."""
    report = EvolutionReport()
    contracts, report.errors = registry.load_contracts()
    for contract_id in sorted(contracts):
        report.contracts.append(evaluate(registry, contracts[contract_id]))
    for path in _stale_baselines(registry, set(registry.entries)):
        report.errors.append(
            f"baseline {path.name} has no registered contract; run 'make evolution-freeze'"
        )
    return report


def _comparable(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {key: snapshot.get(key) for key in _COMPARABLE_KEYS}


def freeze_baselines(registry: Registry) -> tuple[list[pathlib.Path], list[str]]:
    """Record reviewed snapshots and prune stale baselines; refuse policy violations.

    Returns the written paths and the errors; nothing is written when any contract fails.
    """
    contracts, errors = registry.load_contracts()
    payloads: dict[str, dict[str, Any]] = {}
    for contract_id in sorted(contracts):
        current = schema_snapshot(contracts[contract_id])
        history = load_history(registry, contract_id) or []
        if history and _comparable(history[-1]) != _comparable(current):
            errors += _step_errors(contract_id, history[-1], current)[1]
            errors += proto_number_errors(contract_id, [*history, current])
            history = [*history, current]
        elif not history:
            history = [current]
        payloads[contract_id] = {**history[-1], "history": history}
    if errors:
        return [], errors
    registry.evolution_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for contract_id, payload in payloads.items():
        path = baseline_path(registry, contract_id)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    for path in _stale_baselines(registry, set(contracts)):
        path.unlink()
    return written, []
