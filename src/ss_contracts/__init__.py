"""Cross-service message contracts for the ss services.

Contracts are authored as ODCS v3.1 YAML under `contracts/` and generated to Pydantic models
committed under `ss_contracts.models` (subclasses of `ss_contracts.base.ContractModel`), so a
git-tag install needs no generation step and only the base dependency. `ss_contracts.tooling`
validates, generates, and gates contract evolution; it needs the `tooling` extra.
"""

DISTRIBUTION = "ss-common"
