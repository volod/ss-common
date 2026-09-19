# Contracts

Cross-service messages are authored once as ODCS v3.1 YAML, registered, gated by version-bump
rules, and generated to Pydantic and JSON Schema (Python services), Protobuf (the Go agent and
future Rust or C++ consumers), and Avro and Parquet (datasets and benchmarks) by one command.
The generic part of fl-op's contract tooling was ported; its optimization model, xopt bindings,
profiles, plan contract, domain packs, and Elasticsearch generator were not.

The registry holds the eight [site-event contracts](#site-event-contracts) and the
[MQTT topic map](#topic-map) that binds `ss/v1/...` topics to them. The mission and
model-artifact manifests are the next `shared-foundation` task in the staging repository's plan.
The tooling is exercised end to end over the sample tree in `tests/fixtures/contracts/sample/`.

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

- `ContractModel`: base of every generated model. Unknown fields are ignored, not rejected,
  because an added optional field is a minor change that older consumers must tolerate.
  Class attributes `CONTRACT_ID`, `CONTRACT_VERSION`, and `SS_BINDING` (message binding).
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
| `array` | `array` + scalar or `json` `items` | `list[T]` | array | `repeated T` | `array` | `large_list<T>` |

An optional field (`required: false`) is `T | None = None`, a `["null", T]` union, a nullable
Arrow field, and a proto3 `optional` scalar; proto message types and repeated fields have no
separate null state, so an optional object arrives unset and an optional array empty. An array
may hold free-form objects (`items: {logicalType: object, physicalType: json}`): `list[dict[str,
Any]]`, `repeated google.protobuf.Struct`, an Avro array of JSON strings, and an Arrow
`large_list<large_string>`. Nested objects with declared `properties` (as a field or as array
items), nested arrays, and `time` are rejected.

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

## Topic map

`contracts/topics.yaml` (`ss_contracts.tooling.topics`) maps every topic pattern to exactly one
contract with the QoS and retain flag publishers use:

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
the Avro parsing canonical form. Descriptions and other hints are not part of it (patch level).

| Change | Class | Required bump |
| --- | --- | --- |
| none | identical | none; never backwards |
| added optional field, changed constraint, added binding key | backward | at least minor |
| removed field; changed logical type, kind, item kind, requiredness, or proto number; added required field; changed or removed binding key | breaking | major |

`evolution-check` classifies the current contract against the latest reviewed snapshot and
re-checks every adjacent history pair. It also fails on a proto field number that ever named a
different field (reserve it instead), a contract without a baseline, a baseline without history,
and a baseline without a contract. `evolution-freeze` appends the current snapshot to each
history (unchanged when identical), prunes stale baselines, and writes nothing when any contract
violates the policy.

## Modules

| Module | Role |
| --- | --- |
| `ss_contracts/base.py` | `ContractModel`, `ContractBytes`, `ContractTimestamp` |
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

`tests/contracts/` (123 tests) copies the sample tree to a temporary directory and covers: every
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
committed topic builds a concrete topic resolving back to its own contract. The serialization of
today's classes to the golden fixtures is tested in the staging repository (27 tests).

## Result

`make ci` is green on Python 3.11 and 3.13 (185 tests), and `make split-check P=ss-common`
passes in the isolated copy. Evidence: the staging repository's task records
`0004-shared-foundation-contracts-odcs-core` (tooling) and
`0005-shared-foundation-contracts-site-events` (site-event contracts and topic map).
