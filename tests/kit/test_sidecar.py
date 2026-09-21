import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ss_kit.sidecar import (
    HttpSidecarClient,
    load_jsonl_sidecar,
    load_media_jsonl_sidecar,
    sidecar_path,
)


def test_sidecar_rows_are_sorted_and_invalid_lines_skipped(tmp_path: Path) -> None:
    video = tmp_path / "flight.mp4"
    lines = [
        json.dumps({"t": 2.0, "v": "b"}),
        "",
        "{not json",
        json.dumps([1, 2]),
        json.dumps({"timestamp": 1.0, "v": "a"}),
        json.dumps({"t": "bad", "v": "z"}),
        json.dumps({"t": None, "v": "n"}),
    ]
    sidecar_path(video, ".gps.jsonl").write_text("\n".join(lines), encoding="utf-8")

    rows = load_media_jsonl_sidecar(video, ".gps.jsonl")

    assert sidecar_path(video, ".gps.jsonl") == tmp_path / "flight.gps.jsonl"
    assert [row["v"] for row in rows] == ["z", "n", "a", "b"]
    assert load_jsonl_sidecar(tmp_path / "missing.jsonl") == []


def _client(handler: Any, base_url: str = "http://sidecar:9000/") -> HttpSidecarClient:
    return HttpSidecarClient(backend_name=" Pose ", base_url=base_url, timeout_sec=1)


def _mock_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        response: httpx.Response = handler(request)
        return response

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(record), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen


def test_http_sidecar_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stats":
            return httpx.Response(200, json={"frames": 3})
        if request.url.path == "/missing":
            return httpx.Response(404)
        return httpx.Response(500)

    seen = _mock_transport(monkeypatch, handler)
    client = _client(handler)

    assert client.is_configured
    assert asyncio.run(client.stats()) == {"configured": True, "backend": "pose", "frames": 3}
    assert asyncio.run(client.request_json("GET", "/missing", allow_404=True)) is None
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.request_json("POST", "/boom", payload={"a": 1}))
    assert str(seen[0].url) == "http://sidecar:9000/stats"
    assert json.loads(seen[-1].content) == {"a": 1}


def test_unconfigured_client_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _mock_transport(monkeypatch, lambda request: httpx.Response(200, json={}))
    client = HttpSidecarClient(backend_name="x", base_url=None, timeout_sec=1)
    assert not client.is_configured
    assert asyncio.run(client.request_json("GET", "/stats")) is None
    assert asyncio.run(client.stats()) == {"configured": False, "backend": "x"}
    assert seen == []


def test_unwrap_dict_payload() -> None:
    assert HttpSidecarClient.unwrap_dict_payload([1]) is None
    assert HttpSidecarClient.unwrap_dict_payload({"a": 1}) == {"a": 1}
    assert HttpSidecarClient.unwrap_dict_payload({"pose": {"x": 1}}, field="pose") == {"x": 1}
    assert HttpSidecarClient.unwrap_dict_payload({"pose": 3}, field="pose") == {"pose": 3}


def test_sidecar_invalid_numeric_times_sort_as_zero(tmp_path: Path) -> None:
    path = tmp_path / "times.jsonl"
    times = [2, "nan", "inf", "-inf", 10**400, 1]
    path.write_text("\n".join(json.dumps({"t": t, "i": i}) for i, t in enumerate(times)))
    assert [row["i"] for row in load_jsonl_sidecar(path)] == [1, 2, 3, 4, 5, 0]
