"""Framework-free security primitives shared by the ss services.

- `keys_match`: timing-safe comparison of a presented credential with the configured one.
- `sign_hmac_sha256` / `verify_hmac_sha256`: webhook body signatures (`sha256=<hex>` accepted).
- `RateLimiter`: token buckets per client key in a bounded LRU table.
- `resolve_allowed_path`: fail-closed allowlist for user-supplied filesystem paths.
- `stable_point_id`: deterministic 64-bit ids from arbitrary parts (SHA-256).
"""

import hashlib
import hmac
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

SIGNATURE_PREFIX = "sha256="
# Default bound of the per-client rate-limit table; the least recently seen client is evicted.
MAX_RATE_LIMIT_CLIENTS = 50_000
# Hex digits of the SHA-256 digest that form a point id (64 bits). Changing it changes every id.
POINT_ID_HEX_DIGITS = 16


def _as_bytes(value: str | bytes) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else value


def keys_match(presented: str | bytes, expected: str | bytes) -> bool:
    """Timing-safe equality; False when `expected` is empty (nothing is configured)."""
    if not expected:
        return False
    if isinstance(presented, str) and isinstance(expected, str):
        try:
            return hmac.compare_digest(presented, expected)
        except TypeError:
            pass  # non-ASCII text: compare the UTF-8 bytes below instead of failing
    return hmac.compare_digest(_as_bytes(presented), _as_bytes(expected))


def sign_hmac_sha256(secret: str | bytes, body: bytes) -> str:
    """Hex HMAC-SHA256 of `body`."""
    return hmac.new(_as_bytes(secret), body, hashlib.sha256).hexdigest()


def verify_hmac_sha256(secret: str | bytes, body: bytes, signature: str) -> bool:
    """True when `signature` (hex, optionally `sha256=`-prefixed) signs `body`.

    Fail-closed: an empty secret or signature never verifies.
    """
    if not secret or not signature:
        return False
    presented = signature.strip()
    if presented.lower().startswith(SIGNATURE_PREFIX):
        presented = presented[len(SIGNATURE_PREFIX) :]
    return keys_match(presented.lower(), sign_hmac_sha256(secret, body))


@dataclass
class TokenBucket:
    capacity: float
    refill_rate: float
    tokens: float
    last_ts: float

    def allow(self, now: float) -> bool:
        """Refill for the time since the last call, then take one token if available."""
        elapsed = max(0.0, now - self.last_ts)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_ts = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


RateProvider = Callable[[], tuple[float, float]]


class RateLimiter:
    """Token-bucket limiter keyed by client, with a bounded least-recently-used table.

    `rate` is `(per_second, burst)`, or a callable returning it, read when a client's bucket is
    created so a limiter can follow live settings. A burst of 0 means one second's worth.
    """

    def __init__(
        self,
        rate: tuple[float, float] | RateProvider,
        *,
        max_clients: int = MAX_RATE_LIMIT_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_clients < 1:
            raise ValueError("max_clients must be at least 1")
        self._rate = rate
        self.max_clients = max_clients
        self._clock = clock
        self.buckets: OrderedDict[str, TokenBucket] = OrderedDict()

    def _new_bucket(self) -> TokenBucket:
        per_second, burst = self._rate() if callable(self._rate) else self._rate
        capacity = max(1.0, burst if burst > 0 else per_second)
        return TokenBucket(capacity, max(0.0, per_second), capacity, self._clock())

    def evict_oldest(self) -> None:
        """Drop least recently seen clients until one more fits."""
        while self.buckets and len(self.buckets) >= self.max_clients:
            self.buckets.popitem(last=False)

    def check(self, key: str) -> bool:
        """Take one token for `key`; False when the client is over its rate."""
        bucket = self.buckets.get(key)
        if bucket is None:
            self.evict_oldest()
            bucket = self.buckets[key] = self._new_bucket()
        else:
            self.buckets.move_to_end(key)
        return bucket.allow(self._clock())


def parse_path_allowlist(value: str | Iterable[str] | None) -> list[str]:
    """Allowlist entries from a comma-separated string or an iterable; blanks dropped."""
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else value
    return [item.strip() for item in items if item and item.strip()]


def resolve_allowed_path(
    user_path: str | os.PathLike[str],
    allowed: str | Sequence[str] | None,
    *,
    must_be_file: bool = False,
    must_be_dir: bool = False,
) -> str | None:
    """The real absolute path of `user_path` when it lies inside an allowed base, else None.

    Fail-closed: an empty allowlist allows nothing. Symlinks are resolved before the check, so
    a link inside a base that points outside it is rejected.
    """
    bases = parse_path_allowlist(allowed)
    if not bases:
        return None
    resolved = os.path.abspath(os.path.realpath(user_path))
    for base in bases:
        base_abs = os.path.abspath(os.path.realpath(base))
        try:
            inside = os.path.commonpath([base_abs, resolved]) == base_abs
        except ValueError:
            continue
        if not inside:
            continue
        if must_be_file and not os.path.isfile(resolved):
            return None
        if must_be_dir and not os.path.isdir(resolved):
            return None
        return resolved
    return None


def stable_point_id(*parts: Any) -> int:
    """64-bit id from the SHA-256 of `str(part)` values joined with `|` terminators."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"|")
    return int(digest.hexdigest()[:POINT_ID_HEX_DIGITS], 16)
