"""Service-to-service authentication on Azure (ADR-023): the Entra app-role replacement for Lambda invoke IAM.

A caller (agent worker -> gateway, gateway -> tool executor) asks its managed identity for a token for
the callee's app registration; the callee accepts it only if it carries the app role Terraform granted to
that identity. Nothing is shared: no key, no secret, nothing to rotate. Active only when
SECONDCHANCE_SERVICE_AUTH_AUDIENCE is set, so the AWS and Compose paths do not change.
"""

import os
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def token_for(client_id: str) -> str:
    """A token for the callee's app registration, from the identity that holds its app role.

    SECONDCHANCE_SERVICE_IDENTITY_CLIENT_ID names that identity when it is not the container's main one:
    only the agent worker has the `agent` identity attached, so only it can obtain a gateway token.
    """
    from azure.identity import ManagedIdentityCredential

    from secondchance.cloud import azure_credential

    identity = os.environ.get("SECONDCHANCE_SERVICE_IDENTITY_CLIENT_ID")
    credential = ManagedIdentityCredential(client_id=identity) if identity else azure_credential()
    return credential.get_token(f"api://{client_id}/.default").token


@lru_cache
def _jwks(tenant_id: str) -> jwt.PyJWKClient:
    host = os.environ.get("SECONDCHANCE_ENTRA_AUTHORITY_HOST", "login.microsoftonline.com")
    return jwt.PyJWKClient(f"https://{host}/{tenant_id}/discovery/v2.0/keys", cache_keys=True, lifespan=3600)


def verify_service_token(token: str, *, tenant_id: str, client_id: str, role: str, key=None) -> dict:
    """Raises jwt.PyJWTError unless `token` is an application token for `client_id` carrying `role`."""
    host = os.environ.get("SECONDCHANCE_ENTRA_AUTHORITY_HOST", "login.microsoftonline.com")
    signing_key = key if key is not None else _jwks(tenant_id).get_signing_key_from_jwt(token).key
    payload = jwt.decode(
        token, signing_key, algorithms=["RS256"],
        audience=[client_id, f"api://{client_id}"],
        issuer=[f"https://{host}/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"],
        options={"require": ["exp", "iss", "aud"]},
    )
    roles = payload.get("roles")
    if not isinstance(roles, list) or role not in roles:
        raise jwt.InvalidTokenError(f"missing app role {role}")
    if payload.get("scp"):  # a delegated user token is never a service call
        raise jwt.InvalidTokenError("user tokens are not service tokens")
    return payload


def require_service_role(role: str):
    """FastAPI dependency; a no-op unless SECONDCHANCE_SERVICE_AUTH_AUDIENCE is configured."""

    def check(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
        client_id = os.environ.get("SECONDCHANCE_SERVICE_AUTH_AUDIENCE")
        if not client_id:
            return
        if credentials is None:
            raise HTTPException(401, "missing service token", headers={"WWW-Authenticate": "Bearer"})
        try:
            verify_service_token(
                credentials.credentials, tenant_id=os.environ["SECONDCHANCE_ENTRA_TENANT_ID"],
                client_id=client_id, role=role,
            )
        except (jwt.PyJWTError, KeyError) as exc:
            raise HTTPException(401, "invalid service token", headers={"WWW-Authenticate": "Bearer"}) from exc

    return check
