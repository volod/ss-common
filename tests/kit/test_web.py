import asyncio
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from ss_kit.security import RateLimiter
from ss_kit.web import (
    API_KEY_HEADER,
    DEFAULT_SECURITY_HEADERS,
    SecurityHeadersMiddleware,
    api_key_dependency,
    check_api_key,
    client_key,
    rate_limit_dependency,
)


def test_check_api_key() -> None:
    check_api_key("", "", required=False)
    with pytest.raises(HTTPException) as missing:
        check_api_key("x", "", required=True)
    assert missing.value.status_code == 503
    with pytest.raises(HTTPException) as forbidden:
        check_api_key("wrong", "secret", required=True)
    assert forbidden.value.status_code == 403
    check_api_key("secret", "secret", required=True)


def test_client_key_trusts_forwarded_for_only_when_asked() -> None:
    class _Client:
        host = "10.0.0.8"

    request = type(
        "Req",
        (),
        {
            "headers": {"x-forwarded-for": " 1.1.1.1, 2.2.2.2"},
            "client": _Client(),
        },
    )()
    assert client_key(request, trust_proxy_headers=True) == "1.1.1.1"
    assert client_key(request, trust_proxy_headers=False) == "10.0.0.8"
    bare = type("Req", (), {"headers": {}, "client": None})()
    assert client_key(bare) == "unknown"


def test_security_headers_middleware_sets_defaults() -> None:
    seen: list[list[tuple[bytes, bytes]]] = []

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain"), (b"x-frame-options", b"SAMEORIGIN")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = SecurityHeadersMiddleware(app)

    async def run() -> None:
        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                seen.append(list(message["headers"]))

        await middleware({"type": "http"}, None, send)

    asyncio.run(run())
    headers = {name: value for name, value in seen[0]}
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"cache-control"] == b"no-store"
    assert set(DEFAULT_SECURITY_HEADERS) >= {"X-Content-Type-Options", "X-Frame-Options"}


def test_fastapi_dependencies() -> None:
    limiter = RateLimiter((1.0, 1.0))
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.router.dependencies.append(
        Depends(api_key_dependency(lambda: "secret", required=lambda: True))
    )
    app.router.dependencies.append(Depends(rate_limit_dependency(limiter)))

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    denied = client.get("/ping")
    assert denied.status_code == 403
    first = client.get("/ping", headers={API_KEY_HEADER: "secret"})
    assert first.status_code == 200
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["cache-control"] == "no-store"
    second = client.get("/ping", headers={API_KEY_HEADER: "secret"})
    assert second.status_code == 429
