"""`ss-contracts validate`: every check that needs no generated files.

Registry consistency (files exist, stay inside the root, every ODCS file is registered, ids
match), the official ODCS schema and ss authoring rules, generation readiness for every format,
golden-fixture round trips, and the MQTT topic map (`topics.yaml`) when present.
"""

from dataclasses import dataclass, field

from ss_contracts.tooling.gen.checker import FORMATS, generation_errors
from ss_contracts.tooling.golden import check_golden
from ss_contracts.tooling.registry import Registry
from ss_contracts.tooling.topics import load_topic_map, topic_map_errors


@dataclass
class ValidationReport:
    contract_ids: list[str] = field(default_factory=list)
    # Entries in `topics.yaml`; None when the registry has no topic map.
    topic_count: int | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(registry: Registry) -> ValidationReport:
    """Validate the registry; raise TopicMapError when `topics.yaml` is unusable."""
    contracts, errors = registry.load_contracts()
    ready = {}
    for contract_id, spec in sorted(contracts.items()):
        findings = [error for fmt in FORMATS for error in generation_errors(spec, fmt)]
        errors.extend(findings)
        if not findings:
            ready[contract_id] = spec
    errors.extend(check_golden(registry, ready))
    topic_map = load_topic_map(registry.root)
    if topic_map is not None:
        errors.extend(topic_map_errors(topic_map, registry.entries, contracts))
    topic_count = len(topic_map.entries) if topic_map is not None else None
    return ValidationReport(sorted(contracts), topic_count, errors)
