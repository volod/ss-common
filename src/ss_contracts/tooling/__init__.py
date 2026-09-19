"""Contract tooling: ODCS validation, registry, generators, and the evolution gate.

Needs the `tooling` extra (PyYAML, jsonschema, fastavro, pyarrow, grpcio-tools). Services never
import it at runtime; they import the committed models under `ss_contracts.models`.
"""
