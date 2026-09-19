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
import pydantic
import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from ss_contracts.tooling.gen import proto
from ss_contracts.tooling.generate import generate
from ss_contracts.tooling.registry import Registry

from ._contract_fixture import custom, prop
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
        # Drop the package and its submodules so a later import sees regenerated models.
        name = registry.models_dir.name
        for module in [m for m in sys.modules if m == name or m.startswith(f"{name}.")]:
            del sys.modules[module]


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


def test_arrays_of_free_form_objects_reach_every_format(
    registry: Registry, edit_contract: EditContract
) -> None:
    def add_events(doc: dict[str, Any]) -> None:
        doc["schema"][0]["properties"].append(
            {
                "name": "events",
                "logicalType": "array",
                "physicalType": "array",
                "required": False,
                "description": "Free-form event objects.",
                "items": {"logicalType": "object", "physicalType": "json"},
                "customProperties": [
                    {"property": "fieldGeneration", "value": {"proto": {"fieldNumber": 14}}}
                ],
            }
        )

    edit_contract("sample-reading", add_events)
    report = generate(registry)
    assert report.ok, report.errors
    out = registry.generated_dir
    model = _import_models(registry).CONTRACTS["sample-reading"]
    events = [{"event": "alarm", "energy_ratio": 0.5}, {"nested": {"k": [1, 2]}}]
    message = model.model_validate(
        {
            "dev_eui": "a" * 16,
            "received_at": "2026-05-01T12:00:00Z",
            "f_cnt": 1,
            "tags": [],
            "events": events,
        }
    )
    assert message.model_dump(mode="json", exclude_unset=True)["events"] == events
    with pytest.raises(pydantic.ValidationError):
        model.model_validate({**message.model_dump(), "events": ["alarm"]})
    schema = json.loads((out / "jsonschema" / "sample-reading.schema.json").read_text())
    assert schema["properties"]["events"]["anyOf"][0]["items"]["type"] == "object"
    assert (
        "repeated google.protobuf.Struct events = 14;"
        in (out / "proto" / "sample_reading.proto").read_text()
    )
    avro = json.loads((out / "avro" / "sample-reading.avsc").read_text())
    avro_events = next(f for f in avro["fields"] if f["name"] == "events")
    assert avro_events["type"] == ["null", {"type": "array", "items": "string"}]
    arrow = pq.read_schema(out / "parquet" / "sample-reading.schema.parquet")
    assert arrow.field("events").type == pa.large_list(pa.large_string())


def test_package_all_follows_ruff_order(registry: Registry, edit_contract: EditContract) -> None:
    def rename(doc: dict[str, Any]) -> None:
        generation = custom(doc["schema"][0], "schemaGeneration")
        generation["pydantic"]["className"] = "AlphaReading"

    edit_contract("sample-reading", rename)
    assert generate(registry, ["pydantic"]).ok
    command = [VENV_BIN / "ruff", "check", "--select", "RUF022", str(registry.models_dir)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout


def _number(value: int, **extra: Any) -> list[dict[str, Any]]:
    return [{"property": "fieldGeneration", "value": {"proto": {"fieldNumber": value}, **extra}}]


def _scalar(name: str, physical: str, number: int, required: bool = True) -> dict[str, Any]:
    logical = {"string": "string", "double": "number", "long": "integer"}[physical]
    return {
        "name": name,
        "logicalType": logical,
        "physicalType": physical,
        "required": required,
        "description": f"Nested {name}.",
        "customProperties": _number(number),
    }


def _add_records(doc: dict[str, Any]) -> None:
    sha = {**_scalar("sha256", "string", 2), "logicalTypeOptions": {"pattern": "^[0-9a-f]{64}$"}}
    doc["schema"][0]["properties"] += [
        {
            "name": "origin",
            "logicalType": "object",
            "physicalType": "record",
            "required": False,
            "description": "Origin of the local frame.",
            "properties": [
                _scalar("lat", "double", 1),
                _scalar("lon", "double", 2),
                _scalar("alt", "double", 3, required=False),
            ],
            "customProperties": _number(14, recordName="GeoOrigin"),
        },
        {
            "name": "files",
            "logicalType": "array",
            "physicalType": "array",
            "required": True,
            "description": "Files with their digests.",
            "items": {
                "logicalType": "object",
                "physicalType": "record",
                "properties": [_scalar("path", "string", 1), sha, _scalar("size", "long", 3)],
            },
            "logicalTypeOptions": {"minItems": 1},
            "customProperties": _number(15, recordName="FileEntry"),
        },
    ]


_RECORD_MESSAGE: dict[str, Any] = {
    "dev_eui": "a" * 16,
    "received_at": "2026-05-01T12:00:00Z",
    "f_cnt": 1,
    "tags": [],
    "origin": {"lat": 50.45, "lon": 30.52},
    "files": [{"path": "a.mp4", "sha256": "0" * 64, "size": 2**40}],
}


@pytest.fixture
def record_registry(registry: Registry, edit_contract: EditContract) -> Registry:
    """The sample tree with an optional record and an array of records, fully generated."""
    edit_contract("sample-reading", _add_records)
    report = generate(registry)
    assert report.ok, report.errors
    return registry


def test_record_models_validate_nested_messages(record_registry: Registry) -> None:
    package = _import_models(record_registry)
    model = package.CONTRACTS["sample-reading"]
    message = model.model_validate(_RECORD_MESSAGE)
    assert type(message.origin).__name__ == "GeoOrigin"
    assert message.files[0].size == 2**40
    assert message.model_dump(mode="json", exclude_unset=True) == _RECORD_MESSAGE
    for bad in ({"origin": {"lat": 1.0}}, {"files": []}, {"files": [{"path": "a"}]}):
        with pytest.raises(pydantic.ValidationError):
            model.model_validate({**_RECORD_MESSAGE, **bad})
    assert "GeoOrigin" not in package.__all__  # records are reached through their message


def test_record_json_schema_uses_defs(record_registry: Registry) -> None:
    path = record_registry.generated_dir / "jsonschema" / "sample-reading.schema.json"
    schema = json.loads(path.read_text())
    assert schema["$defs"]["FileEntry"]["required"] == ["path", "sha256", "size"]
    assert schema["$defs"]["FileEntry"]["properties"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert schema["properties"]["files"]["items"] == {"$ref": "#/$defs/FileEntry"}


def test_record_protobuf_nests_messages(record_registry: Registry) -> None:
    out = record_registry.generated_dir / "proto"
    proto_text = (out / "sample_reading.proto").read_text()
    assert "  message GeoOrigin {" in proto_text
    assert "  GeoOrigin origin = 14;" in proto_text
    assert "  repeated FileEntry files = 15;" in proto_text
    assert "    optional double alt = 3;" in proto_text
    # A private pool: the default one already holds the sample file from another test.
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    descriptor_set.ParseFromString((out / "sample_reading.pb").read_bytes())
    pool = descriptor_pool.DescriptorPool()
    for file_proto in descriptor_set.file:
        pool.Add(file_proto)
    message_cls = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("ss.contracts.fixtures.v1.SampleReading")
    )
    wire = message_cls(dev_eui="a" * 16, f_cnt=1)
    wire.origin.lat = 50.45
    wire.files.add(path="a.mp4", sha256="0" * 64, size=2**40)
    parsed = message_cls.FromString(wire.SerializeToString())
    assert parsed.HasField("origin") and not parsed.origin.HasField("alt")
    assert parsed.files[0].size == 2**40


def test_record_avro_round_trips(record_registry: Registry) -> None:
    path = record_registry.generated_dir / "avro" / "sample-reading.avsc"
    avro_schema = json.loads(path.read_text())
    avro_files = next(f for f in avro_schema["fields"] if f["name"] == "files")
    assert avro_files["type"]["items"]["name"] == "FileEntry"
    parsed_avro = fastavro.parse_schema(avro_schema)
    record = {f["name"]: None for f in avro_schema["fields"]}
    record.update(
        dev_eui="a" * 16,
        received_at=datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC),
        f_cnt=1,
        tags=[],
        decoded_object="{}",
        origin={"lat": 50.45, "lon": 30.52, "alt": None},
        files=[{"path": "a.mp4", "sha256": "0" * 64, "size": 2**40}],
    )
    buffer = io.BytesIO()
    fastavro.schemaless_writer(buffer, parsed_avro, record)
    buffer.seek(0)
    assert fastavro.schemaless_reader(buffer, parsed_avro)["files"] == record["files"]


def test_record_arrow_structs(record_registry: Registry) -> None:
    out = record_registry.generated_dir / "parquet"
    arrow = pq.read_schema(out / "sample-reading.schema.parquet")
    files_type = arrow.field("files").type
    assert files_type.value_type.field("size").type == pa.int64()
    assert not files_type.value_type.field("path").nullable
    assert arrow.field("origin").type.field("alt").nullable
    descriptor = json.loads((out / "sample-reading.parquet.json").read_text())
    files_entry = next(f for f in descriptor["fields"] if f["name"] == "files")
    assert files_entry["arrow_type"] == "large_list<struct>"
    assert [f["name"] for f in files_entry["fields"]] == ["path", "sha256", "size"]


def test_record_models_are_ruff_and_mypy_clean(record_registry: Registry) -> None:
    models = str(record_registry.models_dir)
    for command in (
        [VENV_BIN / "ruff", "format", "--check", models],
        [VENV_BIN / "ruff", "check", "--select", "E4,E7,E9,F,I,B,UP,SIM,RUF", models],
        [VENV_BIN / "mypy", "--strict", "--no-incremental", "--cache-dir", "/dev/null", models],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr


def test_record_generation_hints_are_checked(
    registry: Registry, edit_contract: EditContract
) -> None:
    def break_hints(doc: dict[str, Any]) -> None:
        _add_records(doc)
        origin = prop(doc, "origin")
        origin["properties"][1]["customProperties"] = []
        origin["properties"][2]["customProperties"] = _number(1)
        custom(origin, "fieldGeneration")["recordName"] = "SampleReading"

    edit_contract("sample-reading", break_hints)
    errors = generate(registry).errors
    assert (
        "sample-reading [pydantic]: field 'origin': recordName 'SampleReading' equals "
        "pydantic.className" in errors
    )
    assert (
        "sample-reading [proto]: field 'origin' record field 'lon': "
        "fieldGeneration.proto.fieldNumber is missing" in errors
    )
    assert (
        "sample-reading [proto]: field 'origin' record field 'alt': "
        "fieldGeneration.proto.fieldNumber 1 is used twice" in errors
    )
