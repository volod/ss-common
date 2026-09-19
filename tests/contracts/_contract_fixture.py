"""Paths and YAML helpers shared by the contract-tooling tests."""

import pathlib
from typing import Any

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "contracts"
SAMPLE = FIXTURES / "sample"


def properties(doc: dict[str, Any]) -> list[dict[str, Any]]:
    props: list[dict[str, Any]] = doc["schema"][0]["properties"]
    return props


def prop(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in properties(doc) if p["name"] == name)


def custom(item: dict[str, Any], name: str) -> Any:
    return next(c["value"] for c in item["customProperties"] if c["property"] == name)
