"""FastAPI integration (`web` extra): security headers, API-key auth, and rate limiting.

```python
app.add_middleware(SecurityHeadersMiddleware)
require_key = api_key_dependency(lambda: settings.API_KEY, required=lambda: settings.AUTH)
limiter = RateLimiter(lambda: (settings.PER_MIN / 60, settings.BURST))
limit = rate_limit_dependency(limiter, trust_proxy_headers=lambda: settings.TRUST_PROXY)
router = APIRouter(dependencies=[Depends(require_key), Depends(limit)])
```

JWT bearer validation lives in `ss_kit.web.jwt`.
"""

from collections.abc import Callable, Mapping

from fastapi import Header, HTTPException, Request, status
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ss_kit.security import RateLimiter, keys_match

API_KEY_HEADER = "X-API-Key"
UNKNOWN_CLIENT = "unknown"
DEFAULT_SECURITY_HEADERS: Mapping[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}

__all__ = [
    "API_KEY_HEADER",
    "DEFAULT_SECURITY_HEADERS",
    "SecurityHeadersMiddleware",
    "api_key_dependency",
    "check_api_key",
    "client_key",
    "rate_limit_dependency",
]


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that sets `headers` on every HTTP response (streaming included)."""

    def __init__(self, app: ASGIApp, headers: Mapping[str, str] | None = None) -> None:
        self.app = app
        pairs = DEFAULT_SECURITY_HEADERS if headers is None else headers
        self._names = {name.lower().encode("latin-1") for name in pairs}
        self._raw = [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in pairs.items()
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in self._names
                ]
                message["headers"] = [*kept, *self._raw]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def client_key(request: Request, *, trust_proxy_headers: bool = False) -> str:
    """The client address for rate limiting.

    Only trust `X-Forwarded-For` behind a reverse proxy that overwrites it; otherwise clients
    can spoof it to dodge or dilute their limit.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client:
        return request.client.host
    return UNKNOWN_CLIENT


def check_api_key(presented: str, expected: str, *, required: bool) -> None:
    """Raise 403 for a wrong key; with no key configured, 503 when auth is required."""
    if not expected:
        if required:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server authentication is not configured",
            )
        return
    if not keys_match(presented, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")


def api_key_dependency(
    expected: Callable[[], str],
    *,
    required: Callable[[], bool] = lambda: False,
    header_name: str = API_KEY_HEADER,
) -> Callable[..., None]:
    """A FastAPI dependency checking `header_name` against `expected()` on every request."""

    def require_api_key(api_key: str = Header(default="", alias=header_name)) -> None:
        check_api_key(api_key, expected(), required=required())

    return require_api_key


def rate_limit_dependency(
    limiter: RateLimiter,
    *,
    enabled: Callable[[], bool] = lambda: True,
    trust_proxy_headers: Callable[[], bool] = lambda: False,
) -> Callable[[Request], None]:
    """A FastAPI dependency that answers 429 once a client exceeds `limiter`."""

    def rate_limit(request: Request) -> None:
        if not enabled():
            return
        key = client_key(request, trust_proxy_headers=trust_proxy_headers())
        if not limiter.check(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded"
            )

    return rate_limit
