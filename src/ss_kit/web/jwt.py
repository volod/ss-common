"""JWT bearer validation (`web` extra, PyJWT).

The validator never trusts the token header's choice of algorithm: `algorithms` is explicit,
`none` is refused, HMAC keys shorter than 32 bytes are refused, and `exp` is always required.

```python
validator = JwtValidator(JwtConfig(key=settings.JWT_PUBLIC_KEY, algorithms=("ES256",),
                                   audience="ss-control", issuer="https://id.example"))
claims = Depends(bearer_claims_dependency(validator))
```
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Header, HTTPException, status

# RFC 7518 section 3.2: an HMAC key must be at least as long as the hash output.
MIN_HMAC_KEY_BYTES = 32
BEARER = "bearer"
_HMAC_PREFIX = "HS"


class JwtConfigError(ValueError):
    """The validator configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class JwtConfig:
    key: str | bytes
    algorithms: Sequence[str]
    audience: str | Sequence[str] | None = None
    issuer: str | None = None
    leeway_sec: float = 0.0
    required_claims: Sequence[str] = field(default_factory=lambda: ("exp",))

    def __post_init__(self) -> None:
        if not self.key:
            raise JwtConfigError("a verification key is required")
        if not self.algorithms:
            raise JwtConfigError("at least one algorithm is required")
        if any(alg.lower() == "none" for alg in self.algorithms):
            raise JwtConfigError("the 'none' algorithm is never accepted")
        hmac_algs = [alg for alg in self.algorithms if alg.upper().startswith(_HMAC_PREFIX)]
        if hmac_algs and len(hmac_algs) != len(self.algorithms):
            # One key cannot safely serve both families (algorithm confusion).
            raise JwtConfigError("HMAC and public-key algorithms cannot share one validator")
        if hmac_algs and len(self._key_bytes()) < MIN_HMAC_KEY_BYTES:
            raise JwtConfigError(f"HMAC keys need at least {MIN_HMAC_KEY_BYTES} bytes")
        if self.leeway_sec < 0:
            raise JwtConfigError("leeway_sec must not be negative")

    def _key_bytes(self) -> bytes:
        return self.key.encode("utf-8") if isinstance(self.key, str) else self.key


class JwtValidator:
    def __init__(self, config: JwtConfig) -> None:
        self.config = config

    def decode(self, token: str) -> dict[str, Any]:
        """Verified claims; raises `jwt.InvalidTokenError` (or a subclass) otherwise."""
        config = self.config
        required = sorted({"exp", *config.required_claims})
        if config.audience is not None:
            required.append("aud")
        if config.issuer is not None:
            required.append("iss")
        claims: dict[str, Any] = jwt.decode(
            token,
            key=config.key,
            algorithms=list(config.algorithms),
            audience=config.audience,
            issuer=config.issuer,
            leeway=config.leeway_sec,
            options={"require": sorted(set(required))},
        )
        return claims


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def bearer_token(authorization: str) -> str:
    """The token of an `Authorization: Bearer <token>` header; 401 when absent or malformed."""
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != BEARER or not token.strip():
        raise _unauthorized("Bearer token required")
    return token.strip()


def bearer_claims_dependency(validator: JwtValidator) -> Callable[..., dict[str, Any]]:
    """A FastAPI dependency returning verified claims, or answering 401."""

    def bearer_claims(authorization: str = Header(default="")) -> dict[str, Any]:
        token = bearer_token(authorization)
        try:
            return validator.decode(token)
        except jwt.InvalidTokenError as exc:
            raise _unauthorized("Invalid token") from exc

    return bearer_claims
