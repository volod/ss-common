"""`ss-contracts validate`: every check that needs no generated files.

Registry consistency (files exist, stay inside the root, every ODCS file is registered, ids
match), the official ODCS schema and ss authoring rules, generation readiness for every format,
and golden-fixture round trips.
"""

from dataclasses import dataclass, field

from ss_contracts.tooling.gen.checker import FORMATS, generation_errors
from ss_contracts.tooling.golden import check_golden
from ss_contracts.tooling.registry import Registry


@dataclass
class ValidationReport:
    contract_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(registry: Registry) -> ValidationReport:
    contracts, errors = registry.load_contracts()
    ready = {}
    for contract_id, spec in sorted(contracts.items()):
        findings = [error for fmt in FORMATS for error in generation_errors(spec, fmt)]
        errors.extend(findings)
        if not findings:
            ready[contract_id] = spec
    errors.extend(check_golden(registry, ready))
    return ValidationReport(sorted(contracts), errors)
