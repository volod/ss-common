from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from ss_kit.web.jwt import (
    JwtConfig,
    JwtConfigError,
    JwtValidator,
    bearer_claims_dependency,
    bearer_token,
)

HMAC_KEY = "k" * 32


def _token(**claims: object) -> str:
    payload = {
        "sub": "agent",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        **claims,
    }
    return jwt.encode(payload, HMAC_KEY, algorithm="HS256")


def test_jwt_config_rejects_unsafe_setup() -> None:
    with pytest.raises(JwtConfigError, match="verification key"):
        JwtConfig(key="", algorithms=("HS256",))
    with pytest.raises(JwtConfigError, match="at least one algorithm"):
        JwtConfig(key=HMAC_KEY, algorithms=())
    with pytest.raises(JwtConfigError, match="none"):
        JwtConfig(key=HMAC_KEY, algorithms=("none",))
    with pytest.raises(JwtConfigError, match="HMAC and public-key"):
        JwtConfig(key=HMAC_KEY, algorithms=("HS256", "RS256"))
    with pytest.raises(JwtConfigError, match="32 bytes"):
        JwtConfig(key="short", algorithms=("HS256",))
    with pytest.raises(JwtConfigError, match="leeway"):
        JwtConfig(key=HMAC_KEY, algorithms=("HS256",), leeway_sec=-1)


def test_validator_round_trip_and_required_claims() -> None:
    validator = JwtValidator(JwtConfig(key=HMAC_KEY, algorithms=("HS256",)))
    assert validator.decode(_token())["sub"] == "agent"
    expired = jwt.encode(
        {"sub": "agent", "exp": datetime.now(UTC) - timedelta(seconds=1)},
        HMAC_KEY,
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        validator.decode(expired)
    missing_exp = jwt.encode({"sub": "agent"}, HMAC_KEY, algorithm="HS256")
    with pytest.raises(jwt.MissingRequiredClaimError):
        validator.decode(missing_exp)


def test_validator_requires_audience_and_issuer() -> None:
    validator = JwtValidator(
        JwtConfig(
            key=HMAC_KEY,
            algorithms=("HS256",),
            audience="ss-control",
            issuer="https://id.example",
        )
    )
    good = _token(aud="ss-control", iss="https://id.example")
    assert validator.decode(good)["aud"] == "ss-control"
    with pytest.raises(jwt.InvalidTokenError):
        validator.decode(_token(aud="other", iss="https://id.example"))


def test_bearer_token_and_dependency() -> None:
    with pytest.raises(HTTPException) as missing:
        bearer_token("")
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException):
        bearer_token("Basic abc")
    assert bearer_token("Bearer  tok  ") == "tok"

    validator = JwtValidator(JwtConfig(key=HMAC_KEY, algorithms=("HS256",)))
    claims_dep = bearer_claims_dependency(validator)
    app = FastAPI()

    @app.get("/me")
    def me(claims: Annotated[dict[str, object], Depends(claims_dep)]) -> dict[str, object]:
        return {"sub": claims["sub"]}

    client = TestClient(app)
    assert client.get("/me").status_code == 401
    ok = client.get("/me", headers={"Authorization": f"Bearer {_token()}"})
    assert ok.status_code == 200
    assert ok.json() == {"sub": "agent"}
    assert client.get("/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
