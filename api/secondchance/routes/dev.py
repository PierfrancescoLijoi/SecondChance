"""Local-only login for the web app (mock OIDC). Never mounted outside SECONDCHANCE_AUTH_MODE=mock,
which itself refuses to start outside SECONDCHANCE_ENV=local (secondchance.auth)."""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from secondchance.auth import mint_token
from secondchance.seed import DEMO_USERS

router = APIRouter(prefix="/dev", tags=["local development"])
_SUBJECT = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=3, max_length=64)


class Token(BaseModel):
    access_token: str
    token_type: str = "Bearer"


@router.get("/users")
def users() -> list[dict]:
    return [{"subject": u["subject"], "role": u["role"]} for u in DEMO_USERS]


@router.post("/token", response_model=Token)
def token(body: TokenRequest) -> Token:
    """Any subject: a new one is a brand-new user who can then register as donor or NGO."""
    if not _SUBJECT.fullmatch(body.subject):
        raise HTTPException(422, "subject: lowercase letters, digits and dashes")
    return Token(access_token=mint_token(body.subject))
