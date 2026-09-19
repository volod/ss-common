import datetime
import importlib
import io
import json
import pathlib
import subprocess
import sys
from typing import Any

import fastavro
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from google.protobuf import descriptor_pb2

from ss_contracts.tooling.gen import proto
from ss_contracts.tooling.generate import generate
from ss_contracts.tooling.registry import Registry

from ._contract_fixture import prop
from .conftest import EditContract

VENV_BIN = pathlib.Path(sys.executable).parent


def _generated(registry: Registry) -> dict[str, bytes]:
    roots = [registry.models_dir, registry.generated_dir]
    return {
        str(path.relative_to(root.parent)): path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix != ".parquet" and "__pycache__" not in path.parts
    }


def _import_models(registry: Registry) -> Any:
    sys.path.insert(0, str(registry.models_dir.parent))
    try:
        importlib.invalidate_caches()
        return importlib.import_module(registry.models_dir.name)
    finally:
        sys.path.remove(str(registry.models_dir.parent))
        sys.modules.pop(registry.models_dir.name, None)


def _golden(registry: Registry, contract_id: str, name: str) -> dict[str, Any]:
    assert registry.golden_dir is not None
    data: dict[str, Any] = json.loads((registry.golden_dir / contract_id / name).read_text())
    return data


def test_every_format_is_generated(registry: Registry) -> None:
    report = generate(registry)
    assert report.ok, report.errors
    names = sorted(p.relative_to(registry.root).as_posix() for p in report.written)
    assert "models/__init__.py" in names
    for expected in (
        "generated/jsonschema/sample-reading.schema.json",
        "generated/avro/sample-reading.avsc",
        "generated/proto/sample_reading.proto",
        "generated/proto/sample_reading.pb",
        "generated/parquet/sample-reading.parquet.json",
        "generated/parquet/sample-reading.schema.parquet",
    ):
        assert expected in names
    assert (registry.generated_dir / "proto" / "sample_reading_pb2.py").is_file()


def test_generation_is_deterministic(registry: Registry) -> None:
    assert generate(registry).ok
    first = _generated(registry)
    assert generate(registry).ok
    assert _generated(registry) == first


def test_generated_models_are_ruff_and_mypy_clean(registry: Registry) -> None:
    assert generate(registry, ["pydantic"]).ok
    models = str(registry.models_dir)
    for command in (
        [VENV_BIN / "ruff", "format", "--check", models],
        [VENV_BIN / "ruff", "check", "--select", "E4,E7,E9,F,I,B,UP,SIM,RUF", models],
        [VENV_BIN / "mypy", "--strict", "--no-incremental", "--cache-dir", "/dev/null", models],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr


def test_models_parse_golden_messages(registry: Registry) -> None:
    assert generate(registry, ["pydantic"]).ok
    package = _import_models(registry)
    reading_cls = package.CONTRACTS["sample-reading"]
    assert (reading_cls.CONTRACT_ID, reading_cls.CONTRACT_VERSION) == ("sample-reading", "1.1.0")
    assert reading_cls.SS_BINDING["modality"] == "lorawan"
    reading = reading_cls.model_validate(_golden(registry, "sample-reading", "full.json"))
    assert reading.received_at.tzinfo is not None
    assert reading.raw_bytes == b"\x01\x02\x03\xff"
    assert reading.install_date == datetime.date(2025, 11, 3)
    # Unknown fields from a newer minor version are ignored, not rejected.
    newer = reading_cls.model_validate({**reading.model_dump(), "added_in_1_2": 1})
    assert not hasattr(newer, "added_in_1_2")


def test_json_schema_carries_contract_identity_and_bindings(registry: Registry) -> None:
    assert generate(registry, ["jsonschema"]).ok
    path = registry.generated_dir / "jsonschema" / "sample-reading.schema.json"
    schema = json.loads(path.read_text())
    assert schema["$id"] == "urn:ss:contracts:fixtures:sample-reading:1.1.0"
    assert schema["x-ss-contract"] == {"id": "sample-reading", "version": "1.1.0"}
    assert schema["x-ss-binding"]["timeBase"] == "utc"
    assert "\n" not in schema["description"]
    props = schema["properties"]
    assert props["rssi"]["anyOf"][0]["maximum"] == 2**31 - 1
    assert props["temperature_c"]["x-ss-binding"] == {"modality": "environmental", "unit": "Cel"}
    assert props["raw_bytes"]["anyOf"][0]["contentEncoding"] == "base64"
    assert sorted(schema["required"]) == ["dev_eui", "f_cnt", "received_at", "tags"]


def test_protobuf_compiles_to_a_descriptor_set(registry: Registry) -> None:
    assert generate(registry, ["proto"]).ok
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    descriptor_set.ParseFromString(
        (registry.generated_dir / "proto" / "sample_detection.pb").read_bytes()
    )
    files = {f.name: f for f in descriptor_set.file}
    assert "google/protobuf/timestamp.proto" in files  # --include_imports
    message = files["sample_detection.proto"].message_type[0]
    assert message.name == "SampleDetection"
    assert {f.name: f.number for f in message.field}["label"] == 4
    assert list(message.reserved_name) == ["score"]
    assert [(r.start, r.end) for r in message.reserved_range] == [(3, 4)]


def test_protobuf_bindings_round_trip_a_message(registry: Registry) -> None:
    assert generate(registry, ["proto"]).ok
    sys.path.insert(0, str(registry.generated_dir / "proto"))
    try:
        module = importlib.import_module("sample_reading_pb2")
    finally:
        sys.path.pop(0)
        sys.modules.pop("sample_reading_pb2", None)
    options = module.DESCRIPTOR.GetOptions()
    assert options.go_package == "github.com/volod/ss-common/gen/go/fixtures/v1;fixturesv1"
    message = module.SampleReading(dev_eui="a84041000181c061", f_cnt=2**40, tags=["a"])
    message.decoded_object.update({"k": 1})
    message.received_at.FromJsonString("2026-05-01T12:00:00Z")
    parsed = module.SampleReading.FromString(message.SerializeToString())
    assert parsed.f_cnt == 2**40
    assert not parsed.HasField("rssi")  # proto3 `optional` keeps presence


def test_protoc_failure_is_reported(registry: Registry, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(spec: Any) -> str:
        return 'syntax = "proto3";\nmessage {\n'

    monkeypatch.setattr(proto, "render", broken)
    report = generate(registry, ["proto"])
    assert any("protoc failed" in error for error in report.errors)


def test_avro_schema_round_trips_a_record(registry: Registry) -> None:
    assert generate(registry, ["avro"]).ok
    schema = json.loads((registry.generated_dir / "avro" / "sample-detection.avsc").read_text())
    assert schema["fields"][-1]["type"] == [
        "null",
        {"type": "array", "items": {"type": "long", "logicalType": "timestamp-micros"}},
    ]
    parsed = fastavro.parse_schema(schema)
    record = {
        "camera_id": "c1",
        "frame_ts_s": 1.5,
        "label": "person",
        "confidence": 0.5,
        "bbox_px": [1, 2, 3, 4],
        "observed_at": [datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC)],
    }
    buffer = io.BytesIO()
    fastavro.schemaless_writer(buffer, parsed, record)
    buffer.seek(0)
    assert fastavro.schemaless_reader(buffer, parsed) == record


def test_parquet_schema_file_matches_the_descriptor(registry: Registry) -> None:
    assert generate(registry, ["parquet"]).ok
    out = registry.generated_dir / "parquet"
    schema = pq.read_schema(out / "sample-reading.schema.parquet")
    descriptor = json.loads((out / "sample-reading.parquet.json").read_text())
    assert [f["name"] for f in descriptor["fields"]] == schema.names
    assert schema.field("received_at").type == pa.timestamp("us", tz="UTC")
    assert schema.field("position").type == pa.large_list(pa.float64())
    assert not schema.field("dev_eui").nullable
    assert json.loads(schema.metadata[b"ss_contract"]) == {
        "id": "sample-reading",
        "version": "1.1.0",
    }
    assert json.loads(schema.field("rssi").metadata[b"ss_binding"]) == {"unit": "dB"}


def test_drift_gate(registry: Registry, edit_contract: EditContract) -> None:
    assert generate(registry, ["pydantic"]).ok
    assert generate(registry, check=True).ok

    edit_contract("sample-reading", lambda doc: prop(doc, "snr").update(description="Changed."))
    report = generate(registry, check=True)
    assert [d for d in report.drift if "sample_reading.py differs" in d], report.drift

    assert generate(registry, ["pydantic"]).ok
    module = registry.models_dir / "sample_detection.py"
    module.write_text(module.read_text() + "# hand edit\n")
    assert not generate(registry, check=True).ok

    assert generate(registry, ["pydantic"]).ok
    (registry.models_dir / "stale_contract.py").write_text("")
    module.unlink()
    drift = generate(registry, check=True).drift
    assert any("sample_detection.py is missing" in d for d in drift)
    assert any("stale_contract.py has no registered contract" in d for d in drift)


def test_regeneration_removes_stale_outputs(registry: Registry) -> None:
    assert generate(registry).ok
    stale = registry.generated_dir / "avro" / "gone.avsc"
    stale.write_text("{}")
    (registry.models_dir / "gone.py").write_text("")
    assert generate(registry).ok
    assert not stale.exists()
    assert not (registry.models_dir / "gone.py").exists()


def test_missing_generation_hints_stop_generation(
    registry: Registry, edit_contract: EditContract
) -> None:
    def drop_number(doc: dict[str, Any]) -> None:
        prop(doc, "label")["customProperties"] = []

    edit_contract("sample-detection", drop_number)
    report = generate(registry, ["proto"])
    assert report.errors == [
        "sample-detection [proto]: field 'label': fieldGeneration.proto.fieldNumber is missing"
    ]
    assert not registry.generated_dir.exists()
