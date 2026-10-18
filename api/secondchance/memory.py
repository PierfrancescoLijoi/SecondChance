"""Memory shared by stateless agents and services (ADR-011).

Every call runs inside a tenant transaction, so RLS decides what exists. Writes are
redacted and always expire; tenant-wide memory only accepts operator-confirmed content.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.privacy import redact

Scope = Literal["run", "conversation", "tenant"]
Kind = Literal["task", "finding", "message", "fact"]

TTL: dict[str, timedelta] = {
    "run": timedelta(days=7),
    "conversation": timedelta(days=30),
    "tenant": timedelta(days=365),
}
EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True)
class Memory:
    id: uuid.UUID
    scope: str
    kind: str
    content: str
    source: str
    created_at: datetime


def _key(scope: Scope, run_id: uuid.UUID | None, subject: str | None) -> dict:
    if scope == "run" and run_id is None:
        raise ValueError("scope 'run' needs run_id")
    if scope == "conversation" and not subject:
        raise ValueError("scope 'conversation' needs subject")
    return {
        "scope": scope,
        "run_id": run_id if scope == "run" else None,
        "subject": subject if scope == "conversation" else None,
    }


def _vector(embedding: list[float]) -> str:
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"embedding must have {EMBEDDING_DIMENSIONS} dimensions")
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def remember(
    session: Session,
    *,
    scope: Scope,
    kind: Kind,
    content: str,
    source: str,
    run_id: uuid.UUID | None = None,
    subject: str | None = None,
    embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> uuid.UUID:
    if scope == "tenant" and source != "operator":
        raise ValueError("tenant memory only accepts operator-confirmed content")
    if (embedding is None) != (embedding_model is None):
        raise ValueError("embedding and embedding_model go together")
    params = _key(scope, run_id, subject) | {
        "kind": kind,
        "content": redact(content),
        "source": source,
        "embedding": _vector(embedding) if embedding is not None else None,
        "embedding_model": embedding_model,
        "ttl": TTL[scope],
    }
    return session.execute(
        text(
            "INSERT INTO agent_memory (scope, run_id, subject, kind, content, source,"
            " embedding, embedding_model, expires_at)"
            " VALUES (:scope, :run_id, :subject, :kind, :content, :source,"
            " CAST(:embedding AS vector), :embedding_model, now() + :ttl)"
            " RETURNING id"
        ),
        params,
    ).scalar_one()


_SELECT = (
    "SELECT id, scope, kind, content, source, created_at FROM agent_memory"
    " WHERE scope = :scope AND expires_at > now()"
    " AND run_id IS NOT DISTINCT FROM :run_id AND subject IS NOT DISTINCT FROM :subject"
)


def recall(
    session: Session,
    *,
    scope: Scope,
    run_id: uuid.UUID | None = None,
    subject: str | None = None,
    kinds: tuple[Kind, ...] | None = None,
    limit: int = 20,
) -> list[Memory]:
    """Newest first, unexpired only."""
    params = _key(scope, run_id, subject) | {"limit": limit, "kinds": list(kinds) if kinds else None}
    rows = session.execute(
        text(
            _SELECT + " AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))"
            " ORDER BY created_at DESC, id LIMIT :limit"
        ),
        params,
    ).mappings()
    return [Memory(**row) for row in rows]


def recall_similar(
    session: Session,
    *,
    scope: Scope,
    embedding: list[float],
    embedding_model: str,
    run_id: uuid.UUID | None = None,
    subject: str | None = None,
    limit: int = 5,
) -> list[tuple[Memory, float]]:
    """Cosine distance, ascending. Vectors from another embedding model are never compared."""
    params = _key(scope, run_id, subject) | {
        "embedding": _vector(embedding),
        "embedding_model": embedding_model,
        "limit": limit,
    }
    rows = session.execute(
        text(
            "SELECT * FROM ("
            "  SELECT id, scope, kind, content, source, created_at,"
            "  embedding <=> CAST(:embedding AS vector) AS distance FROM agent_memory"
            "  WHERE scope = :scope AND expires_at > now()"
            "  AND run_id IS NOT DISTINCT FROM :run_id AND subject IS NOT DISTINCT FROM :subject"
            "  AND embedding_model = :embedding_model"
            ") hits ORDER BY distance LIMIT :limit"
        ),
        params,
    ).mappings()
    return [(Memory(**{k: v for k, v in row.items() if k != "distance"}), row["distance"]) for row in rows]
