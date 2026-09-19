import pathlib
import shutil
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from ss_contracts.tooling.registry import Registry, load_registry

from ._contract_fixture import SAMPLE

EditContract = Callable[[str, Callable[[dict[str, Any]], None]], None]


@pytest.fixture
def sample_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """A private copy of the sample contract tree."""
    root = tmp_path / "contracts"
    shutil.copytree(SAMPLE, root)
    return root


@pytest.fixture
def registry(sample_root: pathlib.Path) -> Registry:
    return load_registry(sample_root)


@pytest.fixture
def edit_contract(sample_root: pathlib.Path) -> EditContract:
    """Rewrite one sample contract through a mutation of its parsed YAML."""

    def edit(contract_id: str, mutate: Callable[[dict[str, Any]], None]) -> None:
        path = sample_root / "odcs" / f"{contract_id}.odcs.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    return edit
