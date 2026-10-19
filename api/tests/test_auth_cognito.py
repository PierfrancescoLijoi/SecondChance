"""The AWS authentication path (ADR-017): RS256 Cognito access tokens against the deploy-time JWKS.

A child interpreter, because secondchance.auth reads its mode at import and the rest of the suite
uses the local mock issuer. The issuer host is .invalid: any network fetch would fail the test.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

API = Path(__file__).resolve().parents[1]
ISSUER = "https://cognito-idp.invalid/eu-central-1_TEST"

CHILD = textwrap.dedent(f"""
    import json, os, time
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing.public_key(), as_dict=True) | {{"kid": "k1", "alg": "RS256", "use": "sig"}}
    os.environ["SECONDCHANCE_COGNITO_JWKS"] = json.dumps({{"keys": [jwk]}})

    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    from secondchance import auth

    def token(kid="k1", **claims):
        now = int(time.time())
        body = {{"iss": "{ISSUER}", "sub": "user-1", "token_use": "access", "client_id": "web-client",
                 "iat": now, "exp": now + 300}} | claims
        return jwt.encode(body, signing, algorithm="RS256", headers={{"kid": kid}})

    def outcome(value):
        try:
            return auth.current_identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials=value)).sub
        except HTTPException as error:
            return error.status_code

    print(json.dumps({{
        "valid": outcome(token()),
        "id_token": outcome(token(token_use="id")),
        "other_client": outcome(token(client_id="other")),
        "unknown_key": outcome(token(kid="k2")),
        "expired": outcome(token(exp=int(time.time()) - 60)),
        "other_issuer": outcome(token(iss="https://cognito-idp.invalid/other")),
    }}))
""")


def test_cognito_access_tokens_are_verified_offline_with_the_deployed_keys() -> None:
    env = os.environ | {
        "SECONDCHANCE_AUTH_MODE": "cognito", "SECONDCHANCE_ENV": "demo",
        "SECONDCHANCE_COGNITO_ISSUER": ISSUER, "SECONDCHANCE_COGNITO_CLIENT_ID": "web-client",
    }
    child = subprocess.run([sys.executable, "-c", CHILD], cwd=API, env=env, capture_output=True, text=True, timeout=60)

    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == {
        "valid": "user-1", "id_token": 401, "other_client": 401,
        "unknown_key": 401, "expired": 401, "other_issuer": 401,
    }
