"""Service-to-service authentication on Azure (ADR-023): who may call this gateway.

The agent worker asks its managed identity for a token for this app registration; the gateway accepts
it only with the app role Terraform granted to that identity. The gateway itself authenticates to the
tool executor the same way. Active only when SECONDCHANCE_SERVICE_AUTH_AUDIENCE is set (AWS and Compose
keep their IAM and private-network boundaries). This package imports no application module, so the
small verifier is deliberately repeated from the API instead of shared.
"""

import os
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def _host() -> str:
    return os.environ.get("SECONDCHANCE_ENTRA_AUTHORITY_HOST", "login.microsoftonline.com")


@lru_cache
def _jwks(tenant_id: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"https://{_host()}/{tenant_id}/discovery/v2.0/keys", cache_keys=True, lifespan=3600)


def token_for(client_id: str) -> str:
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

    if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"):
        credential = ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))
    else:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return credential.get_token(f"api://{client_id}/.default").token


def verify_service_token(token: str, *, tenant_id: str, client_id: str, role: str, key=None) -> dict:
    """Raises jwt.PyJWTError unless `token` is an application token for `client_id` carrying `role`."""
    signing_key = key if key is not None else _jwks(tenant_id).get_signing_key_from_jwt(token).key
    payload = jwt.decode(
        token, signing_key, algorithms=["RS256"],
        audience=[client_id, f"api://{client_id}"],
        issuer=[f"https://{_host()}/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"],
        options={"require": ["exp", "iss", "aud"]},
    )
    roles = payload.get("roles")
    if not isinstance(roles, list) or role not in roles:
        raise jwt.InvalidTokenError(f"missing app role {role}")
    if payload.get("scp"):
        raise jwt.InvalidTokenError("user tokens are not service tokens")
    return payload


def require_service_role(role: str):
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
