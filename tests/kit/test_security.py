import hashlib
import hmac
import os
from pathlib import Path

import pytest

from ss_kit.security import (
    RateLimiter,
    keys_match,
    parse_path_allowlist,
    resolve_allowed_path,
    sign_hmac_sha256,
    stable_point_id,
    verify_hmac_sha256,
)


def test_keys_match() -> None:
    assert keys_match("secret123", "secret123")
    assert not keys_match("wrong", "secret123")
    assert not keys_match("", "secret123")
    assert not keys_match("", "")  # nothing configured never matches
    assert keys_match("päss", "päss")  # non-ASCII text compares as UTF-8
    assert not keys_match("päss", "pass")
    assert keys_match(b"raw", "raw")


def test_hmac_signatures() -> None:
    body = b'{"incident": 1}'
    expected = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert sign_hmac_sha256("topsecret", body) == expected
    assert verify_hmac_sha256("topsecret", body, expected)
    assert verify_hmac_sha256("topsecret", body, f"sha256={expected.upper()}")
    assert not verify_hmac_sha256("topsecret", body + b" ", expected)
    assert not verify_hmac_sha256("", body, expected)
    assert not verify_hmac_sha256("topsecret", body, "")


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_token_bucket() -> None:
    clock = _Clock()
    limiter = RateLimiter((1.0, 2.0), clock=clock)
    assert [limiter.check("a") for _ in range(3)] == [True, True, False]
    assert limiter.check("b")  # clients are independent
    clock.now += 1.0
    assert limiter.check("a")
    assert not limiter.check("a")


def test_rate_limiter_reads_live_rates_and_defaults_burst() -> None:
    rates = [(0.5, 0.0)]
    clock = _Clock()
    limiter = RateLimiter(lambda: rates[0], clock=clock)
    assert limiter.check("a") and not limiter.check("a")  # burst 0 -> capacity 1
    rates[0] = (10.0, 10.0)
    assert sum(limiter.check("new") for _ in range(12)) == 10


def test_rate_limiter_table_is_bounded_lru() -> None:
    limiter = RateLimiter((1.0, 1.0), max_clients=3)
    for key in ("a", "b", "c"):
        limiter.check(key)
    limiter.check("a")  # a becomes most recent
    limiter.check("d")
    assert list(limiter.buckets) == ["c", "a", "d"]
    with pytest.raises(ValueError, match="max_clients"):
        RateLimiter((1.0, 1.0), max_clients=0)


def test_path_allowlist(tmp_path: Path) -> None:
    base = tmp_path / "allowed"
    (base / "sub").mkdir(parents=True)
    video = base / "clip.mp4"
    video.write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "escape").symlink_to(outside)

    assert parse_path_allowlist(f" {base} , ,{outside}") == [str(base), str(outside)]
    assert parse_path_allowlist(None) == []
    assert resolve_allowed_path(video, [str(base)], must_be_file=True) == str(video)
    assert resolve_allowed_path(base / "sub", str(base), must_be_dir=True) == str(base / "sub")
    assert resolve_allowed_path(base / "sub", [str(base)], must_be_file=True) is None
    assert resolve_allowed_path(video, [str(base)], must_be_dir=True) is None
    assert resolve_allowed_path(base / "sub" / ".." / "..", [str(base)]) is None
    assert resolve_allowed_path(base / "escape", [str(base)]) is None
    assert resolve_allowed_path(outside, [str(base), str(outside)]) == str(outside)


def test_empty_allowlist_denies_everything(tmp_path: Path) -> None:
    for allowed in (None, "", [], [" "]):
        assert resolve_allowed_path(tmp_path, allowed) is None
    assert resolve_allowed_path(os.sep, [str(tmp_path)]) is None


def test_stable_point_id() -> None:
    first = stable_point_id("vid1", 0, 1000, "frame")
    assert first == stable_point_id("vid1", 0, 1000, "frame")
    assert first != stable_point_id("vid1", 0, 1001, "frame")
    assert first != stable_point_id("vid1", 0, 1000, "tile", 10, 20)
    assert stable_point_id("ab", "c") != stable_point_id("a", "bc")
    assert 0 <= first < 2**64
    digest = hashlib.sha256(b"vid1|0|1000|frame|").hexdigest()
    assert first == int(digest[:16], 16)
