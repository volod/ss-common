# Runtime helpers (`ss_kit`)

`ss_kit` is the light runtime library of the `ss-common` distribution. It holds env and settings,
`DATA_DIR` paths, silent logging, security primitives, a JSONL/HTTP sidecar client, and hardware
detection. Integrations that need FastAPI, JWT, HTTP, or MQTT live behind extras and are imported
only by the module that uses them.

Code enters `ss_kit` only when at least two service repositories use it, it holds no domain types,
and it adds no heavy dependency. Service settings classes, GPU and torch helpers, and preflight
checks stay in their services.

## Modules

| Module | Holds |
| --- | --- |
| `ss_kit.env` | `.env` dialect (`parse_env_text`, `load_env_files`) and typed getters (`env_str`, `env_bool`, `env_int`, `env_float`, `env_csv`, `env_json_dict`) |
| `ss_kit.settings` | `load_layered_env`, `KitSettings` (flat upper-case attributes, `masked()`, `data_dir()`), `mask_secret` |
| `ss_kit.paths` | `discover_project_root`, `data_dir` / `data_path` (relative `DATA_DIR` joins the project root, never the working directory), `ensure_dir` |
| `ss_kit.logging` | Compact ASCII queue handler; importing the module configures nothing and writes nothing |
| `ss_kit.security` | Timing-safe `keys_match`, HMAC-SHA256 sign/verify, bounded LRU `RateLimiter`, fail-closed `resolve_allowed_path`, `stable_point_id` |
| `ss_kit.sidecar` | JSONL sidecars next to a media file; `HttpSidecarClient` (lazy `httpx`, `web` extra) |
| `ss_kit.hw` | Cgroup-aware memory and CPU; `max_jobs()` / `build_budget()` for heavy C++/CUDA compiles |
| `ss_kit.cli` | `ss-kit` / `python -m ss_kit`: `max-jobs`, `build-budget`, `hw` |
| `ss_kit.quality` | Standard-library plan, doc-link, and footprint gates; see [developer tooling](developer-tooling.md) |
| `ss_kit.web` | `web` extra: security-headers middleware, API-key and rate-limit FastAPI dependencies |
| `ss_kit.web.jwt` | `web` extra: JWT bearer validation (`exp` required, `none` refused, HMAC keys at least 32 bytes) |
| `ss_kit.mqtt` | `mqtt` extra: TLS/mTLS `MqttSettings` for `aiomqtt.Client`, `TopicBuilder` over the committed topic map |

## Environment and settings

`parse_env_text` reads the dialect the ss services use: `KEY=value`, optional `export `, `#`
comments, unquoted values ending at ` #`, single-quoted literals, double-quoted escapes and
multi-line values, and `${NAME}` / `${NAME:-default}` expansion. `load_env_files` applies files in
order without overriding variables already in the process environment.

`read_env_file(..., environ=...)` and `load_env_files(..., environ=...)` use the supplied mapping
for interpolation, including an empty mapping. Later files can reference earlier layers;
existing environment values override earlier layers during expansion. Within one file, earlier
definitions retain precedence. Loading parses every layer before applying changes, so a malformed
quoted value cannot leave the environment partially updated. `load_layered_env` also reads
`APP_ENV` from the supplied mapping; explicit `app_env` takes precedence.

`load_layered_env(project_root)` applies, lowest precedence first:

1. `<package_env_dir>/<APP_ENV>.env` (optional packaged defaults);
2. `<root>/.env`;
3. `<root>/.data/.env`;
4. `<root>/.data/.env.local`.

`KitSettings` is a base for flat namespaces whose attributes read the environment when the class
body runs, so the layers load first. `masked()` redacts names that match the credential pattern
(`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, ...) plus `SECRET_FIELDS`. Service settings classes are not
defined here.

`mask_secret` masks the entire value when `visible_suffix=0`, rejects negative suffix lengths,
and fully masks a one-character value. Other short values retain the existing one-character
suffix behavior.

`data_dir(project_root)` resolves `$DATA_DIR` (default `.data`) against the project root.
`data_path` rejects parts that climb out of it.

## Logging

`configure_logging()` installs a `QueueHandler` so concurrent threads never interleave lines, and
formats records as `mm:ss,mmm LEVEL leaf message` with non-ASCII characters spelled in ASCII. The
optional `banner` is one full-date line so relative timestamps stay anchored. `get_logger` does not
configure handlers. `stop_logging` drains the queue.

ASCII conversion happens after formatting, preserving mapping interpolation keys and covering
logger names, object representations, and exception text. Raw lines and banners are also ASCII.

## Security

- `keys_match` is timing-safe and returns False when the expected value is empty.
- `verify_hmac_sha256` accepts a bare hex digest or a `sha256=` prefix; an empty secret or
  signature never verifies.
- `RateLimiter` keeps one token bucket per client key in a bounded LRU table (default 50_000).
- `resolve_allowed_path` is fail-closed: an empty allowlist allows nothing; symlinks are resolved
  before the check.
- `stable_point_id(*parts)` is the 64-bit integer of the first 16 hex digits of SHA-256 over
  `str(part)` values joined with `|`.

## Sidecars

`load_jsonl_sidecar` reads object rows, skips blanks and invalid lines, and sorts by `t` then
`timestamp`. `HttpSidecarClient` returns None when unconfigured; `httpx` is imported only when a
request is made.

Missing, invalid, overflowing, or non-finite timestamps sort as zero; equal-time rows retain
file order. The first present time key takes precedence even when its value is invalid.

## 0.2.0 review verification

Regression coverage in `tests/kit/test_env.py`, `test_settings_paths.py`, `test_logging.py`, and
`test_sidecar.py` exercises isolated environment mappings, layered interpolation, secret masking,
formatted and raw ASCII logs, and invalid numeric timestamps. Existing consumer call signatures
remain valid; applications using custom environment mappings now get that mapping consistently.
The package metadata targets 0.2.0; consumer release pins require a published tag.
`make ci` passes with 287 tests; 31 focused sensor, fusion, and video consumer tests also pass.
Scope and verification limits are recorded in the [review record](../records/0001-runtime-quality-review.md).

## Hardware and `ss-kit`

`max_jobs()` is the single source of truth for `MAX_JOBS` on heavy compiles: each job is assumed
to peak at 12 GiB, 20% of total memory stays free, and at most `(cores - 2) // 2` jobs run.
Memory and CPU honor cgroup limits (v2 then v1) and the process CPU affinity.

```text
ss-kit max-jobs [--ram-per-job-gb G] [--reserve-frac F]
ss-kit build-budget [--total-kb N --avail-kb N --cpu-cores N] ...
ss-kit hw
```

`build-budget` prints `jobs total_gb avail_gb usable_gb mem_jobs cpu_jobs`. GPU and torch helpers
are out of scope.

## Web extra

`SecurityHeadersMiddleware` is pure ASGI and sets `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, and `Cache-Control: no-store` on every HTTP response, including
streaming. `check_api_key` answers 503 when auth is required but no key is configured, and 403
on a mismatch. `client_key` uses `X-Forwarded-For` only when asked. `JwtValidator` never trusts
the token header's algorithm list.

## MQTT extra

`MqttSettings.from_env(prefix)` reads `<P>HOST`, `<P>PORT` (8883 with TLS, else 1883), user,
password, client id, and TLS/mTLS files. `client_kwargs()` returns keyword arguments for
`aiomqtt.Client`, with a TLS 1.2+ context when TLS is on and with `tls_context` omitted when it
is off, so the settings module itself imports no MQTT library.

`TopicBuilder` builds and resolves `ss/v1/...` topics from
`ss_contracts.models.topic_map` (committed by `ss-contracts generate`, no YAML at runtime).
`from_yaml` reads a site override (`mqtt` extra pulls PyYAML).

## Tests

`tests/kit/` covers the dialect, settings and paths, logging silence and format, security,
sidecars, hardware and the CLI, FastAPI dependencies and headers, JWT, and MQTT TLS/topic
building. `tests/test_packages.py` imports `ss_kit` plus env, settings, paths, logging, security,
hw, sidecar, mqtt, and `ss_contracts.topics` in a fresh interpreter and asserts empty stdout and
stderr and that torch, numpy, transformers, and pydantic stay unloaded.

## Result

`make ci` is green (273 tests). The footprint gate still resolves five packages on aarch64 and
x86_64 Linux. While staged, the task record lives in the parent repository
(`docs/impl/records/0007-shared-foundation-kit-runtime-core.md`).
