# Runtime quality review

## Task and scope

- Source: ad hoc user request; baseline `4493f66`, initially clean ss-common tree.
- State: implemented and verified; awaiting user review before commit.
- Plan counts at start: 0 agent tasks, 0 human tasks; no eligible task in either lane.
- Accepted request:

```text
This is a shared library for https://github.com/volod/ss-fusion, https://github.com/volod/ss-sens, https://github.com/volod/ss-fusion and https://github.com/volod/ss-video. Review, test, and improve the code quality and functionality. Note: We don't need support for v0.1.0 interfaces; we can introduce v0.2.0, refactor the related application, and bump the tag.
```

## Implementation

- Environment interpolation honors explicit mappings and earlier layers. APP_ENV selection
  uses the same supplied environment. Parsing completes before environment mutation.
- Secret masking no longer reveals a whole secret for a zero suffix or a one-character value;
  negative suffix lengths raise ValueError.
- ASCII logging sanitizes the complete rendered record, preserving mapping keys and covering
  exception text, logger names, and object representations. Banners and raw lines are sanitized.
- JSONL sidecar times that overflow or are non-finite sort stably as zero.
- Topic map version and QoS require integers, rejecting boolean, float, and unhashable inputs
  with TopicMapError. Contract definitions, generated models, and wire versions are unchanged.
- Package metadata and uv.lock target 0.2.0, with no dependency version changes. No commit,
  push, or tag is made. Consumer source interfaces need no refactor for these fixes; published
  dependency pins remain v0.1.0 until the user reviews and releases the candidate.

Current behavior: [runtime helpers](../current/kit.md), [contracts](../current/contracts.md),
and [developer tooling](../current/developer-tooling.md).

## Acceptance evidence

- Baseline `make ci`: 273 passed; two upstream deprecation warnings.
- Regression-first checks: seven runtime cases and five malformed topic-map cases failed
  before the fixes. Additional tests preserve environment precedence and atomic loading.
- Final `make ci`: passed, 287 tests and the same two upstream deprecation warnings. Formatting,
  lint, typing, complexity, shell checks, documentation integrity, both architecture footprints,
  contract generation/drift, and evolution checks passed. The final run used network-enabled
  execution for package-index tests after a sandboxed run stalled. Footprint remains five
  lightweight dependencies on both aarch64 and x86_64; no forbidden dependency was introduced.
- Consumer tests use PYTHONPATH to load this working tree without changing consumer installs
  or dependency pins. PYTHONDONTWRITEBYTECODE=1 and `-p no:cacheprovider` avoid checkout writes.
  These are focused compatibility checks, not full consumer CI:
  - ss-sens: `tests/unit/test_site_event_contracts.py`, 5 passed using ss-common's interpreter.
  - ss-fusion: `tests/unit/pipeline/core/test_logging_utils.py` and `test_config.py`, 24 passed
    using its existing interpreter.
  - ss-video: `tests/unit/pipeline/realtime/test_contract_consumer.py`, 2 passed using fusion's
    interpreter and video's source path, with `--noconftest`. The broader selection stalled
    before collection; the unit conftest preloads torchvision. That run was interrupted.
- Consumer test warnings: cache_dir is unknown when the cache plugin is disabled; the sensor
  run also reports asyncio_mode without the async plugin (its selected tests are synchronous).

## Audit and handoff

Review covered runtime helpers, security and web integration, MQTT topic validation, contract
base types, consumer call sites, existing tests, and the complete library gate. Fixes are
bounded to reproducible defects; this is not an exhaustive security audit. Existing unrelated
fusion and video edits were preserved. No new dependencies or service processes were introduced.

Plan counts remain 0 agent and 0 human tasks; no registered capability changed status.
Release creation and consumer pin updates are intentionally left to the user's commit review.
Final diff inspection found only intended ss-common changes, with no generated-model drift.
All test commands finished or were interrupted; no service, port, or background worker remains.
