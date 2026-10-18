"""Knowledge service API (ADR-015): spaces, documents, ingestion jobs, search, answers."""

import os
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.identity import ROLES, Claims, require_roles, tenant_session
from secondchance.knowledge import ingest
from secondchance.knowledge.retrieval import Hit, answer, search
from secondchance.observability import current_correlation_id
from secondchance.queues import Queue, SqsQueue

router = APIRouter(tags=["knowledge"])
TenantSession = Depends(tenant_session, scope="function")
Admin = Depends(require_roles("org_admin", "platform_admin"))
Role = Literal["donor", "coordinator", "volunteer", "center_staff", "org_admin", "platform_admin"]
Language = Literal["en", "da", "pl", "it"]


@lru_cache
def jobs_queue() -> Queue:
    return SqsQueue(os.environ.get("SECONDCHANCE_QUEUE_JOBS", "jobs"))


class SpaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["public", "ngo_private", "territorial", "donor", "shared"]
    allowed_roles: list[Role] = Field(min_length=1, max_length=len(ROLES))
    territory: str | None = Field(default=None, max_length=20)


class SpaceAcl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_roles: list[Role] = Field(min_length=1, max_length=len(ROLES))


class Space(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    kind: str
    visibility: str
    allowed_roles: list[str]
    territory: str | None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    space_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    language: Language | None = None
    territory: str | None = Field(default=None, max_length=20)
    top_k: int = Field(default=8, ge=1, le=20)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1000)
    space_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    language: Language | None = None
    territory: str | None = Field(default=None, max_length=20)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    version: int | None
    section_path: list[str]
    page_start: int
    page_end: int
    language: str
    snippet: str
    score: float

    @classmethod
    def of(cls, hit: Hit) -> "SearchHit":
        return cls(**{k: v for k, v in hit.__dict__.items() if k in cls.model_fields}, snippet=hit.content[:600])


class AnswerView(BaseModel):
    answer: str | None
    abstained: bool
    reason: str | None
    mode: Literal["generated", "extractive", "none"]
    sources: list[SearchHit]
    cited: list[int]
    model_id: str | None
    # AI Act art. 50: the interface must say this text was produced by an AI system.
    generated_by: Literal["secondchance-knowledge"] = "secondchance-knowledge"


class Job(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version: int
    status: str
    error_category: str | None = None
    page_count: int | None = None
    quality: dict | None = None
    created_at: datetime | None = None
    published_at: datetime | None = None


class Document(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    title: str
    language: str
    document_type: str
    territory: str | None
    active_version: int | None
    created_at: datetime


@router.get("/knowledge/spaces", response_model=list[Space])
def get_spaces(session: Session = TenantSession) -> list[dict]:
    rows = session.execute(
        text("SELECT id, tenant_id, name, kind, visibility, allowed_roles, territory FROM knowledge_space ORDER BY name")
    ).mappings()
    return [dict(r) for r in rows]


@router.post("/knowledge/spaces", response_model=Space, status_code=201)
def post_space(body: SpaceCreate, session: Session = TenantSession, claims: Claims = Admin) -> dict:
    if body.kind == "public":
        platform = session.execute(text("SELECT kind = 'platform' FROM tenant")).scalar_one_or_none()
        if claims.role != "platform_admin" or not platform:
            raise HTTPException(403, "public spaces are curated by platform admins")
    row = session.execute(
        text(
            "INSERT INTO knowledge_space (name, kind, visibility, allowed_roles, territory)"
            " VALUES (:name, :kind, :visibility, :roles, :territory)"
            " RETURNING id, tenant_id, name, kind, visibility, allowed_roles, territory"
        ),
        {"name": body.name, "kind": body.kind, "visibility": "public" if body.kind == "public" else "tenant",
         "roles": sorted(set(body.allowed_roles)), "territory": body.territory},
    ).mappings().one()
    return dict(row)


@router.post("/knowledge/spaces/{space_id}/acl", status_code=204)
def post_space_acl(space_id: uuid.UUID, body: SpaceAcl, claims: Claims = Admin) -> None:
    ingest.set_space_acl(claims, space_id, sorted(set(body.allowed_roles)))


@router.post("/knowledge/search", response_model=list[SearchHit])
def post_search(body: SearchRequest, session: Session = TenantSession) -> list[SearchHit]:
    hits = search(session, body.query, space_ids=body.space_ids, language=body.language,
                  territory=body.territory, top_k=body.top_k)
    return [SearchHit.of(h) for h in hits]


@router.post("/knowledge/answer", response_model=AnswerView)
def post_answer(body: AnswerRequest, session: Session = TenantSession) -> AnswerView:
    result = answer(session, body.question, space_ids=body.space_ids, language=body.language, territory=body.territory)
    return AnswerView(answer=result.text, abstained=result.abstained, reason=result.reason, mode=result.mode,
                      sources=[SearchHit.of(h) for h in result.sources], cited=result.cited, model_id=result.model_id)


def _enqueue(job: dict, message: dict | None, queue: Queue) -> dict:
    if message is not None:
        queue.send(message)  # after the commit; the requeue job covers a failed send
    return job


@router.post("/documents", response_model=Job, status_code=202)
def post_document(
    file: Annotated[UploadFile, File()],
    space_id: Annotated[uuid.UUID, Form()],
    title: Annotated[str, Form(min_length=2, max_length=200)],
    language: Annotated[Language, Form()],
    document_type: Annotated[Literal["guideline", "regulation", "manual", "procedure", "other"], Form()],
    territory: Annotated[str | None, Form(max_length=20)] = None,
    source_uri: Annotated[str | None, Form(max_length=500)] = None,
    claims: Claims = Admin,
    queue: Queue = Depends(jobs_queue),
) -> dict:
    meta = ingest.DocumentMeta(space_id, title, language, document_type, territory, source_uri)
    job, message = ingest.upload(claims, file.file.read(), meta, None, current_correlation_id())
    return _enqueue(job, message, queue)


@router.post("/documents/{document_id}/versions", response_model=Job, status_code=202)
def post_version(
    document_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    claims: Claims = Admin,
    queue: Queue = Depends(jobs_queue),
) -> dict:
    job, message = ingest.upload(claims, file.file.read(), None, document_id, current_correlation_id())
    return _enqueue(job, message, queue)


@router.post("/documents/{document_id}/delete", status_code=204)
def post_delete(document_id: uuid.UUID, claims: Claims = Admin) -> None:
    ingest.delete_document(claims, document_id)


@router.get("/documents", response_model=list[Document])
def get_documents(session: Session = TenantSession) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT id, space_id, title, language, document_type, territory, active_version, created_at"
            " FROM document WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 200"
        )
    ).mappings()
    return [dict(r) for r in rows]


@router.get("/ingestion/jobs/{job_id}", response_model=Job)
def get_job(job_id: uuid.UUID, session: Session = TenantSession, claims: Claims = Admin) -> dict:
    row = session.execute(
        text(
            "SELECT id, document_id, version, status, error_category, page_count, quality, created_at, published_at"
            " FROM document_version WHERE id = :id"
        ),
        {"id": job_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "ingestion job not found")
    return dict(row)

