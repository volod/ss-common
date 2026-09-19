"""The evolution policy: contract snapshots, change classes, and required version bumps.

A snapshot records the version, the message binding, and per field the logical type, canonical
physical kind, array item kind, requiredness, `logicalTypeOptions`, binding, and proto field
number, plus structural fingerprints. Descriptions and generation hints other than field numbers
are not part of it, so editing them is a patch-level change. A step between two snapshots is:

- identical: the version may stay or move forward, never backward;
- backward-compatible (an added optional field, a changed `logicalTypeOptions` constraint, or an
  added binding key): at least a minor bump;
- breaking (a removed field; a changed logical type, kind, item kind, requiredness, or proto field
  number; an added required field; a changed or removed binding key): a major bump.

A change without a version bump always fails, and so does a proto field number that ever named a
different field, since reusing it corrupts old readers on the wire.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ss_contracts.tooling.fingerprint import contract_fingerprints
from ss_contracts.tooling.odcs import ContractSpec, FieldSpec

CHANGE_IDENTICAL = "identical"
CHANGE_BACKWARD = "backward"
CHANGE_BREAKING = "breaking"
_ORDER = {CHANGE_IDENTICAL: 0, CHANGE_BACKWARD: 1, CHANGE_BREAKING: 2}

# Field attributes whose change breaks existing producers or consumers.
_BREAKING_ATTRS = ("logicalType", "physicalType", "items", "required", "protoFieldNumber")


@dataclass
class ChangeReport:
    change_class: str = CHANGE_IDENTICAL
    details: list[str] = field(default_factory=list)

    def note(self, change_class: str, detail: str) -> None:
        self.details.append(detail)
        if _ORDER[change_class] > _ORDER[self.change_class]:
            self.change_class = change_class


def _field_snapshot(fld: FieldSpec) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "logicalType": fld.logical_type,
        "physicalType": fld.kind,
        "required": fld.required,
    }
    if fld.item_kind:
        entry["items"] = fld.item_kind
    if fld.options:
        entry["options"] = {key: fld.options[key] for key in sorted(fld.options)}
    if fld.binding:
        entry["binding"] = dict(fld.binding)
    number = fld.generation.get("proto", {}).get("fieldNumber")
    if isinstance(number, int):
        entry["protoFieldNumber"] = number
    return entry


def schema_snapshot(spec: ContractSpec) -> dict[str, Any]:
    """The version-relevant shape of a contract."""
    snapshot: dict[str, Any] = {
        "contractId": spec.contract_id,
        "version": spec.version,
        "binding": dict(spec.binding),
        "fields": {fld.name: _field_snapshot(fld) for fld in spec.fields},
    }
    fingerprints = contract_fingerprints(spec)
    if fingerprints:
        snapshot["fingerprints"] = fingerprints
    return snapshot


def _classify_binding(
    label: str, old: Mapping[str, Any], new: Mapping[str, Any], report: ChangeReport
) -> None:
    for key in sorted(set(old) | set(new)):
        if key not in new:
            report.note(CHANGE_BREAKING, f"{label} binding removed '{key}'")
        elif key not in old:
            report.note(CHANGE_BACKWARD, f"{label} binding added '{key}'")
        elif old[key] != new[key]:
            report.note(
                CHANGE_BREAKING, f"{label} binding '{key}' changed '{old[key]}' -> '{new[key]}'"
            )


def _classify_field(
    name: str, old: Mapping[str, Any], new: Mapping[str, Any], report: ChangeReport
) -> None:
    for attr in _BREAKING_ATTRS:
        if old.get(attr) != new.get(attr):
            report.note(
                CHANGE_BREAKING,
                f"field '{name}' {attr} changed {old.get(attr)!r} -> {new.get(attr)!r}",
            )
    if old.get("options", {}) != new.get("options", {}):
        report.note(CHANGE_BACKWARD, f"field '{name}' constraints changed")
    _classify_binding(f"field '{name}'", old.get("binding", {}), new.get("binding", {}), report)


def _classify_added(name: str, new: Mapping[str, Any], report: ChangeReport) -> None:
    if new.get("required"):
        report.note(CHANGE_BREAKING, f"added required field '{name}'")
    else:
        report.note(CHANGE_BACKWARD, f"added optional field '{name}'")


def classify_change(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> ChangeReport:
    """Classify the delta between two snapshots."""
    report = ChangeReport()
    old_fields: Mapping[str, Any] = baseline.get("fields") or {}
    new_fields: Mapping[str, Any] = current.get("fields") or {}
    for name in sorted(old_fields.keys() - new_fields.keys()):
        report.note(CHANGE_BREAKING, f"removed field '{name}'")
    for name in sorted(old_fields.keys() & new_fields.keys()):
        _classify_field(name, old_fields[name], new_fields[name], report)
    for name in sorted(new_fields.keys() - old_fields.keys()):
        _classify_added(name, new_fields[name], report)
    old_binding = baseline.get("binding") or {}
    _classify_binding("message", old_binding, current.get("binding") or {}, report)
    return report


def parse_version(text: str) -> tuple[int, int, int]:
    parts = [int(part) if part.isdigit() else 0 for part in (text or "").split(".")[:3]]
    parts += [0] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def version_policy_errors(
    contract_id: str, old_version: str, new_version: str, change: ChangeReport
) -> list[str]:
    """Enforce the bump policy for one step; returns human-readable errors."""
    old, new = parse_version(old_version), parse_version(new_version)
    step = f"({old_version} -> {new_version})"
    if change.change_class == CHANGE_IDENTICAL:
        return [f"{contract_id}: version went backwards {step}"] if new < old else []
    if new <= old:
        return [
            f"{contract_id}: {change.change_class} change without a version bump {step}; changes: {change.details}"
        ]
    if change.change_class == CHANGE_BREAKING and new[0] <= old[0]:
        return [
            f"{contract_id}: breaking change needs a major version bump {step}; changes: {change.details}"
        ]
    if change.change_class == CHANGE_BACKWARD and new[:2] <= old[:2]:
        return [
            f"{contract_id}: backward-compatible change needs at least a minor version bump {step}; changes: {change.details}"
        ]
    return []


def proto_number_errors(contract_id: str, snapshots: list[Mapping[str, Any]]) -> list[str]:
    """A proto field number that named different fields across the history."""
    owners: dict[int, tuple[str, str]] = {}
    errors: list[str] = []
    for snapshot in snapshots:
        for name, spec in (snapshot.get("fields") or {}).items():
            number = spec.get("protoFieldNumber")
            if not isinstance(number, int):
                continue
            previous = owners.setdefault(number, (name, str(snapshot.get("version"))))
            if previous[0] != name:
                errors.append(
                    f"{contract_id}: proto field number {number} was '{previous[0]}' in "
                    f"{previous[1]} and is '{name}' in {snapshot.get('version')}; reserve it instead"
                )
    return sorted(set(errors))
