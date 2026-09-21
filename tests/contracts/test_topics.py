import logging
import pathlib
from typing import Any

import pytest
import yaml

from ss_contracts.tooling.cli import main
from ss_contracts.tooling.generate import generate
from ss_contracts.tooling.registry import load_registry
from ss_contracts.tooling.topics import (
    TopicEntry,
    TopicMapError,
    load_topic_map,
    patterns_overlap,
)
from ss_contracts.tooling.validate import validate
from ss_contracts.topics import committed_topic_map

from ._contract_fixture import custom
from .conftest import EditContract

PROJECT_CONTRACTS = pathlib.Path(__file__).resolve().parents[2] / "contracts"
READING = "ss/v1/site/{site_id}/sensor/{dev_eui}/reading"
DETECTION = "ss/v1/site/{site_id}/camera/{camera_id}/detection"


def _entry(pattern: str, contract: str, **extra: Any) -> dict[str, Any]:
    return {"pattern": pattern, "contract": contract, "qos": 1, "retain": False, **extra}


def _write(root: pathlib.Path, topics: Any, version: Any = 1) -> None:
    doc = {"topicsVersion": version, "topics": topics}
    (root / "topics.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")


@pytest.fixture
def named_detection(edit_contract: EditContract) -> None:
    """Give sample-detection a buildable topic (its sample binding uses `+`)."""

    def mutate(doc: dict[str, Any]) -> None:
        custom(doc["schema"][0], "ssBinding")["mqttTopic"] = DETECTION

    edit_contract("sample-detection", mutate)


def _errors(root: pathlib.Path) -> list[str]:
    return validate(load_registry(root)).errors


@pytest.mark.usefixtures("named_detection")
def test_valid_topic_map(sample_root: pathlib.Path) -> None:
    _write(sample_root, [_entry(READING, "sample-reading"), _entry(DETECTION, "sample-detection")])
    report = validate(load_registry(sample_root))
    assert report.ok, report.errors
    assert report.topic_count == 2


def test_absent_topic_map_is_not_checked(sample_root: pathlib.Path) -> None:
    report = validate(load_registry(sample_root))
    assert report.ok and report.topic_count is None


FINDINGS: dict[str, tuple[list[dict[str, Any]], str]] = {
    "unregistered": ([_entry("ss/v1/x/{id}", "ghost")], "contract 'ghost' is not registered"),
    "prefix": ([_entry("site/{id}", "sample-reading")], "must start with 'ss/'"),
    "anonymous level": ([_entry("ss/v1/+/x", "sample-reading")], "level '+' must be a literal"),
    "multi level": ([_entry("ss/v1/x/#", "sample-reading")], "level '#' must be a literal"),
    "repeated name": (
        [_entry("ss/v1/{id}/x/{id}", "sample-reading")],
        "placeholder names ['id'] repeat",
    ),
    "listed twice": (
        [_entry("ss/v1/x/{a}", "sample-reading"), _entry("ss/v1/x/{a}", "sample-reading")],
        "listed more than once",
    ),
    "overlap": (
        [_entry("ss/v1/x/{a}/y", "sample-reading"), _entry("ss/v1/x/z/{b}", "sample-reading")],
        "can match the same topic",
    ),
    "binding not mapped": (
        [_entry(DETECTION, "sample-detection")],
        f"sample-reading: ssBinding.mqttTopic {READING} must be its only topic",
    ),
    "binding mapped twice": (
        [_entry(READING, "sample-reading"), _entry("ss/v1/extra/{dev_eui}", "sample-reading")],
        "must be its only topic in topics.yaml, found",
    ),
}


@pytest.mark.usefixtures("named_detection")
@pytest.mark.parametrize("case", sorted(FINDINGS))
def test_topic_map_findings(sample_root: pathlib.Path, case: str) -> None:
    topics, expected = FINDINGS[case]
    _write(sample_root, topics)
    errors = _errors(sample_root)
    assert any(expected in error for error in errors), errors


UNUSABLE: dict[str, tuple[Any, Any, str]] = {
    "version": ([], 2, "topicsVersion must be 1"),
    "version bool": ([], True, "topicsVersion must be 1"),
    "version float": ([], 1.0, "topicsVersion must be 1"),
    "topics type": ({}, 1, "'topics' must be a list"),
    "entry type": (["x"], 1, "topics[0] must be a mapping"),
    "pattern type": ([{"contract": "sample-reading"}], 1, "needs string 'pattern'"),
    "qos range": ([_entry(READING, "sample-reading", qos=3)], 1, "qos must be 0, 1, or 2"),
    "qos bool": ([_entry(READING, "sample-reading", qos=True)], 1, "qos must be 0, 1, or 2"),
    "qos float": ([_entry(READING, "sample-reading", qos=1.0)], 1, "qos must be 0, 1, or 2"),
    "qos list": ([_entry(READING, "sample-reading", qos=[])], 1, "qos must be 0, 1, or 2"),
    "qos mapping": ([_entry(READING, "sample-reading", qos={})], 1, "qos must be 0, 1, or 2"),
    "retain": ([_entry(READING, "sample-reading", retain="yes")], 1, "retain must be true"),
    "description": ([_entry(READING, "sample-reading", description=1)], 1, "description must"),
}


@pytest.mark.parametrize("case", sorted(UNUSABLE))
def test_unusable_topic_map(sample_root: pathlib.Path, case: str) -> None:
    topics, version, expected = UNUSABLE[case]
    _write(sample_root, topics, version)
    with pytest.raises(TopicMapError, match=expected.replace("[", r"\[")):
        load_topic_map(sample_root)


def test_cli_exits_2_on_an_unusable_topic_map(
    sample_root: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(sample_root, [], version=0)
    assert main(["--root", str(sample_root), "validate"]) == 2
    assert "topicsVersion must be 1" in caplog.text


def test_cli_reports_topic_findings(
    sample_root: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    _write(sample_root, [_entry(READING, "ghost")])
    assert main(["--root", str(sample_root), "validate"]) == 1
    assert "contract 'ghost' is not registered" in caplog.text


def test_build_match_and_resolve() -> None:
    entry = TopicEntry(READING, "sample-reading", 1, False)
    topic = entry.build(site_id="farm-1", dev_eui="70b3d57ed0060001")
    assert topic == "ss/v1/site/farm-1/sensor/70b3d57ed0060001/reading"
    assert entry.match(topic) == {"site_id": "farm-1", "dev_eui": "70b3d57ed0060001"}
    assert entry.match("ss/v1/site/farm-1/sensor/x/state") is None
    assert entry.match("ss/v1/site/farm-1/sensor/reading") is None
    assert entry.match("ss/v1/site/+/sensor/x/reading") is None
    with pytest.raises(ValueError, match="missing"):
        entry.build(site_id="farm-1")
    with pytest.raises(ValueError, match="unexpected"):
        entry.build(site_id="a", dev_eui="b", extra="c")
    with pytest.raises(ValueError, match="not a single topic level"):
        entry.build(site_id="a/b", dev_eui="c")


def test_patterns_overlap() -> None:
    def overlap(first: str, second: str) -> bool:
        return patterns_overlap(TopicEntry(first, "a", 0, False), TopicEntry(second, "b", 0, False))

    assert overlap("ss/v1/{a}/x", "ss/v1/y/{b}")
    assert overlap("ss/v1/{a}", "ss/v1/{b}")
    assert not overlap("ss/v1/{a}/x", "ss/v1/{a}/y")
    assert not overlap("ss/v1/{a}", "ss/v1/{a}/x")


def test_committed_topic_map_resolves_every_topic_to_one_contract() -> None:
    registry = load_registry(PROJECT_CONTRACTS)
    topic_map = load_topic_map(PROJECT_CONTRACTS)
    assert topic_map is not None
    contracts, errors = registry.load_contracts()
    assert errors == []
    # Every message bound to a topic is mapped; the file manifests are not messages.
    topic_bound = {cid for cid, spec in contracts.items() if spec.binding.get("mqttTopic")}
    assert {entry.contract for entry in topic_map.entries} == topic_bound
    assert set(registry.entries) - topic_bound == {"mission-bundle", "model-artifact"}
    for entry in topic_map.entries:
        params = {name: f"{name}-1" for name in entry.placeholders}
        resolved = topic_map.resolve(entry.build(**params))
        assert resolved == (entry, params)
    retained = {entry.contract for entry in topic_map.entries if entry.retain}
    assert retained == {"sensor-state"}
    runtime = committed_topic_map()
    wire = [(entry.pattern, entry.contract, entry.qos, entry.retain) for entry in topic_map.entries]
    assert [
        (entry.pattern, entry.contract, entry.qos, entry.retain) for entry in runtime.entries
    ] == wire


@pytest.mark.usefixtures("named_detection")
def test_generate_commits_the_runtime_topic_map(sample_root: pathlib.Path) -> None:
    _write(sample_root, [_entry(READING, "sample-reading"), _entry(DETECTION, "sample-detection")])
    registry = load_registry(sample_root)
    report = generate(registry, formats=["pydantic"])
    assert report.ok, report.errors
    module = registry.models_dir / "topic_map.py"
    assert module.is_file()
    check = generate(registry, formats=["pydantic"], check=True)
    assert check.ok and not check.drift
    module.write_text(module.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8")
    stale = generate(registry, formats=["pydantic"], check=True)
    assert any("topic_map.py" in finding for finding in stale.drift)
