"""Authentication only (ADR-017): a valid token proves the subject, nothing more.

Tenant and role come from memberships in the database (secondchance.identity).
- mock (local): HS256 with a shared secret, refused outside SECONDCHANCE_ENV=local;
- cognito (AWS): RS256 access tokens checked against the user pool's JWKS.
"""

import os
import sys
import time
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

MODE = os.environ.get("SECONDCHANCE_AUTH_MODE", "mock")
ENV = os.environ.get("SECONDCHANCE_ENV", "local")

if MODE == "mock":
    ISSUER = os.environ.get("SECONDCHANCE_JWT_ISSUER", "http://localhost:8000/mock-oidc")
    AUDIENCE = os.environ.get("SECONDCHANCE_JWT_AUDIENCE", "secondchance-api")
    SECRET = os.environ["SECONDCHANCE_JWT_SECRET"]
    # The shared-secret mock must never protect real data.
    if ENV != "local":
        raise RuntimeError("the HS256 mock OIDC is for local runs only; set SECONDCHANCE_AUTH_MODE=cognito")
    if len(SECRET) < 32:
        raise RuntimeError("SECONDCHANCE_JWT_SECRET must be at least 32 characters")
elif MODE == "cognito":
    ISSUER = os.environ["SECONDCHANCE_COGNITO_ISSUER"]  # https://cognito-idp.<region>.amazonaws.com/<pool id>
    CLIENT_ID = os.environ["SECONDCHANCE_COGNITO_CLIENT_ID"]
else:
    raise RuntimeError(f"unknown SECONDCHANCE_AUTH_MODE {MODE!r}")

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str | None = None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


@lru_cache
def _deployed_jwks() -> jwt.PyJWKSet | None:
    # On AWS Terraform reads the pool's public keys at deploy time: the function runs in a VPC
    # without NAT, and a user pool with a domain is not reachable through PrivateLink.
    keys = os.environ.get("SECONDCHANCE_COGNITO_JWKS")
    return jwt.PyJWKSet.from_json(keys) if keys else None


def _signing_key(token: str):
    deployed = _deployed_jwks()
    if deployed is None:
        return _jwks().get_signing_key_from_jwt(token).key
    kid = jwt.get_unverified_header(token).get("kid")
    matches = [key for key in deployed.keys if key.key_id == kid]
    if not matches:
        raise jwt.InvalidTokenError("unknown signing key")
    return matches[0].key


def verify(token: str) -> dict:
    if MODE == "cognito":
        key = _signing_key(token)
        payload = jwt.decode(
            token, key, algorithms=["RS256"], issuer=ISSUER, options={"require": ["exp", "iss", "sub", "token_use"]}
        )
        # Cognito access tokens carry client_id instead of aud.
        if payload.get("token_use") != "access" or payload.get("client_id") != CLIENT_ID:
            raise jwt.InvalidTokenError("not an access token for this app")
        return payload
    return jwt.decode(
        token, SECRET, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
        options={"require": ["exp", "iss", "aud", "sub"]},
    )


def current_identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Identity:
    if credentials is None:
        raise _unauthorized("missing bearer token")
    try:
        payload = verify(credentials.credentials)
        sub = payload["sub"]
        if not isinstance(sub, str) or not 0 < len(sub) <= 255:
            raise ValueError("bad subject")
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _unauthorized("invalid token") from exc
    email = payload.get("email") if isinstance(payload.get("email"), str) else None
    return Identity(sub=sub, email=email)


def mint_token(sub: str, ttl_seconds: int = 3600, email: str | None = None) -> str:
    """Mock OIDC issuer for local runs and tests; on AWS, Cognito issues tokens."""
    if MODE != "mock":
        raise RuntimeError("tokens are minted only by the local mock issuer")
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": AUDIENCE, "sub": sub, "iat": now, "exp": now + ttl_seconds}
    if email:
        payload["email"] = email
    return jwt.encode(payload, SECRET, algorithm="HS256")


if __name__ == "__main__":
    # python -m secondchance.auth <subject>
    print(mint_token(sys.argv[1]))
