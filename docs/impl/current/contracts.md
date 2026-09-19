# Contracts

Cross-service messages and file manifests are authored once as ODCS v3.1 YAML, registered, gated by version-bump
rules, and generated to Pydantic and JSON Schema (Python services), Protobuf (the Go agent and
future Rust or C++ consumers), and Avro and Parquet (datasets and benchmarks) by one command.
The generic part of fl-op's contract tooling was ported; its optimization model, xopt bindings,
profiles, plan contract, domain packs, and Elasticsearch generator were not.

The registry holds the eight [site-event contracts](#site-event-contracts), the
[MQTT topic map](#topic-map) that binds `ss/v1/...` topics to them, and the two
[manifest contracts](#manifest-contracts) for mission bundles and model artifacts. The tooling is
exercised end to end over the sample tree in `tests/fixtures/contracts/sample/`.

## Layout

| Path | Holds | Committed |
| --- | --- | --- |
| `contracts/registry.yaml` | Registry: every contract, its ODCS file and owner, and the output paths | yes |
| `contracts/topics.yaml` | [Topic map](#topic-map): `ss/v1/...` pattern to contract, QoS, and retain | yes |
| `contracts/odcs/<id>.odcs.yaml` | One ODCS contract per message | yes |
| `contracts/evolution/<id>.json` | Reviewed baseline: latest snapshot plus `history` | yes |
| `src/ss_contracts/models/` | Generated Pydantic models, one module per contract, and `CONTRACTS` | yes, drift-gated |
| `contracts/generated/{jsonschema,avro,proto,parquet}/` | Generated schemas | no (gitignored) |
| `tests/fixtures/contracts/golden/<id>/*.json` | Golden messages (`goldenDir`) | yes |
| `tests/fixtures/contracts/sample/` | Sample tree for the tooling tests | yes |

Relative paths in `registry.yaml` resolve against its directory; an ODCS path must stay inside
it. `registryVersion: 1`, `jsonSchemaIdBase`, `modelsDir`, and `generatedDir` are required,
`goldenDir` is optional, and each entry needs `odcs` (a relative `*.odcs.yaml` path) and `owner`
(the producing service). A registry key must equal its contract's `id`, and every ODCS file under
`odcs/` must be registered.

## Runtime package

The base install (pydantic only) imports the models. `ss_contracts.base` defines:

- `ContractRecord`: base of the records nested in a message (and of `ContractModel`). Unknown
  fields are ignored, not rejected, because an added optional field is a minor change that older
  consumers must tolerate.
- `ContractModel`: base of every generated model, with class attributes `CONTRACT_ID`,
  `CONTRACT_VERSION`, and `SS_BINDING` (message binding).
- `ContractBytes`: bytes that serialize to standard base64 in JSON, the alphabet the Protobuf
  JSON mapping emits (Pydantic's own base64 mode writes the URL-safe alphabet); both alphabets
  decode.
- `ContractTimestamp`: an aware datetime whose JSON Schema requires an explicit offset through a
  pattern, since `format: date-time` alone is only an annotation for most validators.

`ss_contracts.models.CONTRACTS` maps contract ids to model classes. Importing `ss_contracts`
loads neither pydantic nor the tooling.

## Authoring rules

`ss_contracts.tooling.rules` and `odcs` accept a contract when it passes the vendored official
ODCS v3.1.0 JSON Schema (`src/ss_contracts/tooling/schemas/`, Apache-2.0, sha256 in `NOTICE`)
and these rules: `apiVersion: v3.1.0`; kebab-case `id`; `MAJOR.MINOR.PATCH` `version`; `status`
in `draft`, `active`, `deprecated`, `retired`; `description.purpose`; exactly one schema object
with at least one property; snake-case, unique property names that are not Python keywords,
proto3 reserved words, Pydantic attributes, or type names the generated module uses; a
`description` and an explicit `required` on every property; ASCII source.

| ODCS `logicalType` | `physicalType` (kind) | Pydantic | JSON Schema | Protobuf | Avro | Arrow |
| --- | --- | --- | --- | --- | --- | --- |
| `string` | `string` | `str` | string | `string` | `string` | `large_string` |
| `string` | `bytes` | `ContractBytes` | string, base64 | `bytes` | `bytes` | `large_binary` |
| `integer` | `int` (`integer`) | `int`, int32 bounds | integer | `int32` | `int` | `int32` |
| `integer` | `long` | `int`, int64 bounds | integer | `int64` | `long` | `int64` |
| `number` | `float` / `double` | `float` | number | `float` / `double` | `float` / `double` | `float32` / `float64` |
| `boolean` | `boolean` (`bool`) | `bool` | boolean | `bool` | `boolean` | `bool` |
| `timestamp` | `timestamp` | `ContractTimestamp` | string, RFC 3339 with offset | `google.protobuf.Timestamp` | `long` `timestamp-micros` | `timestamp[us, tz=UTC]` |
| `date` | `date` | `datetime.date` | string, date | `string` (ISO 8601) | `int` `date` | `date32` |
| `object` | `json` | `dict[str, Any]` | object | `google.protobuf.Struct` | `string` (JSON text) | `large_string` (JSON text) |
| `object` | `record` + `properties` | `ContractRecord` subclass | object in `$defs` | nested message | nested `record` | `struct` |
| `array` | `array` + scalar, `json`, or `record` `items` | `list[T]` | array | `repeated T` | `array` | `large_list<T>` |

An optional field (`required: false`) is `T | None = None`, a `["null", T]` union, a nullable
Arrow field, and a proto3 `optional` scalar; proto message types and repeated fields have no
separate null state, so an optional object arrives unset and an optional array empty. An array
may hold free-form objects (`items: {logicalType: object, physicalType: json}`): `list[dict[str,
Any]]`, `repeated google.protobuf.Struct`, an Avro array of JSON strings, and an Arrow
`large_list<large_string>`. Nested arrays and `time` are rejected, and so are declared
`properties` on a free-form object.

### Records

An object with declared properties is a record: `physicalType: record` on the property, or on
`items` for an array of records. Its `properties` follow the same rules as message fields
(snake-case unique names, description, explicit `required`, types, options, and bindings), with
their own `fieldGeneration.proto.fieldNumber` numbered within the record. Records nest one level:
a record's property may not be a record or an array of records. The record's type name is
`fieldGeneration.recordName` on the property, PascalCase, unique in the contract, and different
from the message's type name in each format; it names the Pydantic class (defined in the same
module before the message class and not exported from the package), the Protobuf message nested
in the contract message, and the Avro record. `items.description` documents one record of an
array (the field's description otherwise). An optional record is `T | None`, a `["null",
record]` union, a nullable Arrow struct, and an unset Protobuf message field. The Parquet
descriptor lists a record's own `fields` under its entry with `arrow_type` `struct` or
`large_list<struct>`.

`logicalTypeOptions` map to Pydantic and JSON Schema constraints: strings `minLength`,
`maxLength`, `pattern`, `format` (schema annotation); numbers and integers `minimum`, `maximum`,
`exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`; arrays `minItems`, `maxItems`; timestamps
`timezone` (must not be `false`). Other keys are rejected. Integer fields without an explicit
bound get the int32 or int64 range, so a message valid in Python also fits the wire type.

### ssBinding

The `ssBinding` custom property on `schema[0]` carries `timeBase`, `frame`, `modality`, and
`mqttTopic`; on a property it carries `timeBase`, `frame`, `unit`, and `modality`.

| Key | Values |
| --- | --- |
| `timeBase` | `utc`, `gps`, `tai`, `monotonic`, `media` |
| `frame` | `wgs84`, `enu`, `image` |
| `unit` | UCUM-style code (`m`, `dB`, `Cel`, `{pixel}`); numeric fields only |
| `modality` | lowercase identifier (`acoustic`, `camera`, `lorawan`) |
| `mqttTopic` | `ss/...`; `+` and `{name}` match one level, a final `#` the rest |

Bindings reach every output: `SS_BINDING` and `x-ss-binding` in the models and JSON Schema,
`ssBinding` attributes in Avro (outside the parsing canonical form), and `ss_binding` field
metadata in Arrow and the Parquet descriptor.

### Generation hints

| Format | `schemaGeneration` on `schema[0]` | `fieldGeneration` per property |
| --- | --- | --- |
| `pydantic`, `jsonschema` | `pydantic.className` | -- |
| `avro` | `avro.namespace`, `avro.recordName` | -- |
| `proto` | `proto.package`, `proto.messageName`; optional `goPackage`, `reserved`, `reservedNames` | `proto.fieldNumber` (unique, 1 to 536870911, outside 19000-19999, not reserved) |
| `parquet` | -- | -- |
| all but `parquet` | -- | `recordName` on a [record](#records) |

## Commands

| Command | Does |
| --- | --- |
| `make contracts` | `ss-contracts validate` (registry, ODCS schema and rules, hints for every format, golden round trips, topic map), then `ss-contracts generate --check` (drift gate) |
| `make contracts-gen` | `ss-contracts generate`: models, then JSON Schema, Avro, Protobuf (compiled), and Parquet |
| `make evolution-check` | `ss-contracts evolution-check` |
| `make evolution-freeze` | `ss-contracts evolution-freeze`, after review |

`make ci` runs `contracts`, `contracts-gen`, and `evolution-check` in that order, so drift fails
before regeneration. The CLI is `ss-contracts [--root DIR] validate | generate [--format FMT]...
[--check] | evolution-check | evolution-freeze`; `--root` defaults to `$SS_CONTRACTS_ROOT`, else
`contracts/` under the project root. It logs through `logging` like the quality gates and exits 0
clean, 1 on findings, and 2 on an unusable registry or topic map or a missing `tooling` extra,
which it names with the install hint instead of a traceback.

## Generation

`generate` writes the models (one module per contract, `sensor-reading` to `sensor_reading.py`,
plus `__init__.py`) and, per format, clears the files that format owns in its generated
directory before writing:

- `jsonschema/<id>.schema.json`: draft 2020-12 from the generated model, with `$id`
  `<jsonSchemaIdBase>:<id>:<version>`, `x-ss-contract`, and bindings;
- `avro/<id>.avsc`: parsed by fastavro before writing;
- `proto/<module>.proto`: compiled by the protoc bundled with grpcio-tools and its well-known
  includes (no system protoc) into `<module>.pb` (descriptor set with `--include_imports`) and
  `<module>_pb2.py`; a protoc failure is a finding;
- `parquet/<id>.parquet.json` (descriptor) and `<id>.schema.parquet` (empty file whose footer
  holds the Arrow schema, readable with `pyarrow.parquet.read_schema`).

Output is deterministic, and the models are `ruff format`-clean and pass strict mypy, so the
drift gate is a text comparison: a contract edited without regenerating, a hand edit, a missing
module, or a module without a contract fails `generate --check`.

## Golden fixtures

With `goldenDir` set, every registered contract needs `<goldenDir>/<id>/` with at least one
`*.json` message. Each must validate against the generated model and JSON Schema and round-trip:
`model_dump(mode="json", exclude_unset=True)` equals the file, so fixtures are canonical
(timestamps with `Z`, standard base64). `*.invalid.json` counter-examples must be rejected by
both. A golden directory without a contract fails.

## Site-event contracts

The messages that cross service boundaries at a site, each derived field for field from the
class that produces it today in the staging repository. All are version `1.0.0`, `active`, domain
`site`, Protobuf package `ss.contracts.site.v1` (Go package
`github.com/volod/ss-common/gen/go/site/v1;sitev1`), and Avro namespace `ss.contracts.site`.

| Contract | Owner | Derived from (staging repository) | Model |
| --- | --- | --- | --- |
| `sensor-reading` | ss-sens | `SensorReading`, `src/sencoop/sensors/lorawan_decoder.py` | `SensorReading` |
| `sensor-state` | ss-sens | `SensorSummary`, the sensor half of `src/sencoop/mesh/site_state.py` | `SensorState` |
| `camera-event` | ss-sens | `CameraEvent`, `src/sencoop/sensors/frigate_events.py` | `CameraEvent` |
| `acoustic-observation` | ss-sens | `AcousticObservation`, `src/sencoop/sensors/sound_analyzer.py` | `AcousticObservation` |
| `sensor-event` | ss-sens | `SensorEvent.to_dict()`, `src/selfsuvis/pipeline/realtime/events.py` | `SensorEvent` |
| `threat-event` | ss-fusion | `ThreatEvent.to_dict()`, same module | `ThreatEvent` |
| `event-envelope` | ss-fusion | `EventEnvelope`, `src/selfsuvis/app/routers/v1/schemas.py` | `EventEnvelope` |
| `scene-caption` | ss-video | a `scene_timeline` row as `RtspCaptioner` writes it | `SceneCaption` |

Wire conventions and decisions:

- Field names, types, and requiredness follow the source class. A field the class always sets
  (including dataclass defaults such as `decoded_object` or `acoustic_events`) is required; a
  field that may be `None` is optional, and a publisher omits it when unset rather than sending
  `null`, which is also what proto3 and the golden fixtures carry.
- Constraints are the ones the producers already guarantee: scores and confidence in 0-1,
  latitude and longitude ranges, non-negative counters and ages, the `new|update|end` event type,
  and the `event_kind` discriminators `sensor` and `threat`. Timestamps need an explicit offset.
- `sensor-state` is one retained message per device instead of the `SiteState` list: the rules
  forbid arrays of declared objects, and a retained per-device topic gives a new subscriber every
  sensor without a snapshot service. Counts and `active_motion` are derived by the consumer.
- `camera-event` keeps `region` (numeric `x`, `y`, `width`, `height`) and the complete NVR message
  in `raw` as free-form objects; `acoustic-observation` carries `acoustic_events` as an array of
  free-form objects (`{"event", "energy_ratio"}`).
- `event-envelope` has no modality field, as in the API body: the modality is the last level of
  its topic, like the `POST /api/v1/events/{modality}` path parameter.
- Units and frames are declared per field in `ssBinding` (`dB`, `Cel`, `%`, `[ppm]`, `hPa`, `V`,
  `deg`, `m`, `s`; `wgs84`, `image`); `scene-caption.t_sec` has time base `media`.

Golden fixtures under `tests/fixtures/contracts/golden/<id>/` were captured from the current code
in the staging repository by `tests/unit/contracts/test_site_event_contracts.py`, which builds
each message through the producing code path (the ChirpStack and Frigate decoders, the site-state
aggregator, `SoundAnalyzer._process_chunk`, the realtime conversions in `coop_ingest`, the API
schema, and the captioner's row write), asserts that it emits no field outside the contract, that
it validates, and that it equals the fixture, and rebuilds each class from its fixture.
`SS_UPDATE_GOLDEN=1` rewrites the fixtures from the code. Each contract also has
`*.invalid.json` counter-examples for its main constraints (14 valid and 14 invalid messages).

## Manifest contracts

Files that move between services for deep analysis and model hand-off. Both are version `1.0.0`,
`active`, carry no `mqttTopic` (they are files, not messages), and use [records](#records).

| Contract | Owner | Domain, Protobuf package, Avro namespace | Model | Written as |
| --- | --- | --- | --- | --- |
| `mission-bundle` | ss-video | `mission`, `ss.contracts.mission.v1`, `ss.contracts.mission` | `MissionBundle` | `mission.json` at the bundle root |
| `model-artifact` | ss-fusion | `model`, `ss.contracts.model.v1`, `ss.contracts.model` | `ModelArtifact` | `<model file>.manifest.json` next to the file |

`mission-bundle` fields: `mission_id`; `created_at`; `time_base` (a binding time base; `media`
today, since every sidecar row time is seconds from its video's start); optional `start_time`
(container creation time of the first video); `platform` (`Platform`: `robot_id` as in the
`missions` table, optional `camera_model` from container tags); optional `origin` (`GeoOrigin`:
`lat`, `lon`, `alt`, `wgs84`), the first GPS fix of the first video, which platform fusion and
`missions.gps_origin_json` use as the ENU origin; `videos` (at least one `BundleVideo`:
`video_id`, file fields, optional `duration_sec`, `fps`, `width`, `height`, and `gps_source`
`srt` or `atom`); and `sidecars` (`BundleSidecar`: `video_id`, `kind`, `format` `jsonl` or
`srt`, file fields, `row_count`, optional `t_start_sec` and `t_end_sec`).

`model-artifact` fields: `artifact_id` (the `model_checkpoints` version id, or the file stem);
`format` `pytorch` or `onnx`; file fields; `base_model` (the hub model the weights were actually
loaded from); `producer` (dotted module); `created_at`; optional `derived_from` (`ArtifactRef`:
`path`, `sha256` of the checkpoint or float ONNX file it was made from); optional
`training_data` (`TrainingDataRef`: `kind`, `ref`, optional `sample_count`); `metrics` (a
`Metric` list of `name` and `value`, empty when none); optional `image_size`, `opset`, and
`quantization`.

File fields are `path`, `sha256` (lowercase hex), and `size_bytes`. A `path` is POSIX and
relative to the manifest's directory, with no leading `/`, no backslash, and no segment starting
with a dot; only `derived_from.path` may start with `../` segments, since a checkpoint often lives
outside the export directory. A consumer resolves every path against the manifest's directory and
checks the digest before reading the file.

Golden fixtures under `tests/fixtures/contracts/golden/`:

| Fixture | Source |
| --- | --- |
| `mission-bundle/local-run-nar.json` | the real local run's input video, built by the staging repository's builder |
| `mission-bundle/tests-assets.json` | the staging repository's `tests/assets/` videos |
| `mission-bundle/sidecars-and-gps.json` | one test video with the repository's IMU, barometer, wind, and environment sidecar generators (the last under `sensors/`) and a DJI srt file |
| `model-artifact/onnx-export-nar.json`, `onnx-int8-nar.json` | written by `export_onnx.py` exporting and INT8-quantizing the real run's SSL checkpoint on a CUDA host |
| `model-artifact/finetune-checkpoint.json` | the FINETUNE handler's manifest builder with fixed inputs |

The staging repository's `tests/unit/contracts/test_manifest_contracts.py` rebuilds the
deterministic fixtures from the code, checks that the export fixtures chain (INT8 to float ONNX
to checkpoint), and exercises both writers. Each contract also has `*.invalid.json`
counter-examples (6 valid and 12 invalid manifests).

## Topic map

`contracts/topics.yaml` (`ss_contracts.tooling.topics`) maps every topic pattern to exactly one
contract with the QoS and retain flag publishers use; every contract with an `ssBinding.mqttTopic`
is mapped, and the manifest contracts, which have none, are not:

| Pattern | Contract | QoS | Retain |
| --- | --- | --- | --- |
| `ss/v1/site/{site_id}/sensor/{dev_eui}/reading` | `sensor-reading` | 1 | no |
| `ss/v1/site/{site_id}/sensor/{dev_eui}/state` | `sensor-state` | 1 | yes |
| `ss/v1/site/{site_id}/camera/{camera}/event` | `camera-event` | 1 | no |
| `ss/v1/site/{site_id}/camera/{camera}/acoustic` | `acoustic-observation` | 1 | no |
| `ss/v1/site/{site_id}/node/{node_id}/sensor-event` | `sensor-event` | 1 | no |
| `ss/v1/site/{site_id}/sector/{sector_id}/threat` | `threat-event` | 1 | no |
| `ss/v1/site/{site_id}/zone/{zone_id}/event/{modality}` | `event-envelope` | 1 | no |
| `ss/v1/site/{site_id}/mission/{mission_id}/scene-caption` | `scene-caption` | 1 | no |

A level is a literal or a named `{placeholder}`; the anonymous `+` and `#` wildcards are not
allowed, so every pattern can build a concrete topic as well as match one. An entry without a
string `pattern` and `contract`, a `qos` of 0, 1, or 2, and a boolean `retain` makes the map
unusable (exit 2). `validate` reports a malformed pattern, repeated placeholder names, a pattern
listed twice, an unregistered contract, two patterns that can match the same concrete topic, and
a contract whose `ssBinding.mqttTopic` is not its one mapped pattern. `TopicEntry.build(**params)`
and `match(topic)` and `TopicMap.resolve(topic)` are the helpers the `ss_kit.mqtt` topic builder
(`kit-runtime-core`) will wrap; a placeholder value must be one level without `/`, `+`, or `#`.

## Evolution

A snapshot records the version, the message binding, and per field the logical type, kind, item
kind, requiredness, `logicalTypeOptions`, binding, and proto field number, plus the SHA-256 of
the Avro parsing canonical form. A record field also records its `recordName` and its own
fields, classified by the same rules under a dotted name (`videos.sha256`). Descriptions and other
hints are not part of it (patch level).

| Change | Class | Required bump |
| --- | --- | --- |
| none | identical | none; never backwards |
| added optional field, changed constraint, added binding key | backward | at least minor |
| removed field; changed logical type, kind, item kind, requiredness, proto number, or record name; added required field; changed or removed binding key | breaking | major |

`evolution-check` classifies the current contract against the latest reviewed snapshot and
re-checks every adjacent history pair. It also fails on a proto field number that ever named a
different field in the message or in one record (reserve it instead), a contract without a baseline, a baseline without history,
and a baseline without a contract. `evolution-freeze` appends the current snapshot to each
history (unchanged when identical), prunes stale baselines, and writes nothing when any contract
violates the policy.

## Modules

| Module | Role |
| --- | --- |
| `ss_contracts/base.py` | `ContractRecord`, `ContractModel`, `ContractBytes`, `ContractTimestamp` |
| `ss_contracts/tooling/types.py` | Formats, logical types, kinds, aliases, integer bounds |
| `ss_contracts/tooling/binding.py` | `ssBinding` validation |
| `ss_contracts/tooling/rules.py` | Official schema validation and authoring rules |
| `ss_contracts/tooling/odcs.py` | Loading and normalization (`ContractSpec`, `FieldSpec`) |
| `ss_contracts/tooling/registry.py` | Registry parsing and consistency |
| `ss_contracts/tooling/gen/` | `checker` (hint readiness) and the `pydantic_gen`, `jsonschema_gen`, `avro`, `proto`, `parquet` generators |
| `ss_contracts/tooling/generate.py` | Writing every format and the drift gate |
| `ss_contracts/tooling/golden.py`, `validate.py` | Golden fixtures; the `validate` command |
| `ss_contracts/tooling/topics.py` | Topic map loading, checks, and topic build and match |
| `ss_contracts/tooling/fingerprint.py`, `evolution_policy.py`, `evolution.py` | Fingerprints; snapshots, classes, and bump rules; baselines, check, freeze |
| `ss_contracts/tooling/cli.py` | `ss-contracts` |

The `tooling` extra holds fastavro, grpcio-tools, jsonschema, pyarrow, and PyYAML; the base
install is unchanged (`make footprint`: five packages on aarch64 and x86_64).

## Tests

`tests/contracts/` (145 tests) copies the sample tree to a temporary directory and covers: every
authoring rule and binding rule; registry consistency and unusable registries; generation of
every format, determinism, ruff and strict-mypy cleanliness of the models, a Protobuf descriptor
set with reserved numbers and names, a `_pb2` round trip with `go_package` and field presence, a
protoc failure, an Avro record round trip, and the Parquet footer schema; the drift gate (edited
contract, hand edit, missing and stale modules); golden round trips and counter-examples; every
change class with its required bump, including a planted field removal without a major bump,
proto number reuse, tampered history, missing and stale baselines, and freeze behavior; the CLI,
its exit codes, and the missing-extra hint; the runtime wire encodings; and the committed tree.
They also cover arrays of free-form objects in every format and their rejection with declared
properties, the ruff `__all__` order of the generated package, every topic-map finding and
unusable-map case with the CLI exit codes, topic build, match, and overlap, and that every
committed topic builds a concrete topic resolving back to its own contract. Records are covered
by every rule (missing properties or name, nesting, nested property rules, duplicate names), the
generation hints (nested field numbers, name collisions), each format (model validation, `$defs`,
a nested Protobuf round trip in a private descriptor pool, an Avro round trip, Arrow structs,
ruff and strict mypy), and each evolution class under dotted names, including a record rename
and a record proto number reuse. The serialization of today's classes and manifests to the
golden fixtures is tested in the staging repository (27 site-event and 12 manifest tests).

## Result

`make ci` is green on Python 3.11 and 3.13 (207 tests), and `make split-check P=ss-common`
passes in the isolated copy. Evidence: the staging repository's task records
`0004-shared-foundation-contracts-odcs-core` (tooling),
`0005-shared-foundation-contracts-site-events` (site-event contracts and topic map), and
`0006-shared-foundation-contracts-mission-artifacts` (records and manifest contracts).
