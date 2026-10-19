"""Document upload and asynchronous ingestion (ADR-015, ADR-016).

Upload (API, synchronous, cheapest checks first): role -> quota -> PDF structure -> space
ACL -> idempotency -> original to object storage -> version row -> job message.
Processing (jobs worker): claim with a lease -> malware verdict (AWS) -> parse -> quality gate ->
chunk -> embed -> one transaction that writes the chunks, publishes the version and retires the
previous one.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import text

from secondchance import storage
from secondchance.admission import LIMITS, admit_upload, reject
from secondchance.db import tenant_transaction
from secondchance.principal import Claims
from secondchance.knowledge.embeddings import as_pgvector, provider
from secondchance.knowledge.pdf import PIPELINE_VERSION, UploadRejected, parse, quality, validate_pdf
from secondchance.knowledge.text import chunk_sections
from secondchance.observability import meter

log = logging.getLogger(__name__)
LEASE = timedelta(minutes=10)
# GuardDuty usually tags a PDF within seconds; a slower verdict is picked up by the requeue job.
SCAN_WAIT = timedelta(seconds=40)
SCAN_POLL_SECONDS = 4
SYSTEM_ROLE = "system"

ingestions = meter.create_counter("secondchance.ingestion.versions", description="Ingested document versions by outcome")


@dataclass(frozen=True)
class DocumentMeta:
    space_id: uuid.UUID
    title: str
    language: str
    document_type: str
    territory: str | None = None
    source_uri: str | None = None


def upload(claims: Claims, data: bytes, meta: DocumentMeta | None, document_id: uuid.UUID | None, correlation_id: str) -> tuple[dict, dict | None]:
    """Returns (job view, queue message or None when the same bytes were already ingested)."""
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        admit_upload(session)
        try:
            pages = validate_pdf(data, LIMITS["pdf_pages"])
        except UploadRejected as rejected:
            raise reject("upload", rejected.reason, status=422) from None
        digest = hashlib.sha256(data).hexdigest()

        if document_id is None:
            space = session.execute(
                text("SELECT visibility, allowed_roles FROM knowledge_space WHERE id = :id AND tenant_id = current_tenant_id()"),
                {"id": meta.space_id},
            ).mappings().one_or_none()
            if space is None:
                raise HTTPException(404, "knowledge space not found in this network")
            document_id = session.execute(
                text(
                    "INSERT INTO document (space_id, title, language, document_type, territory, source_uri,"
                    " visibility, allowed_roles, created_by)"
                    " VALUES (:space, :title, :language, :type, :territory, :source, :visibility, :roles, :by) RETURNING id"
                ),
                {"space": meta.space_id, "title": meta.title, "language": meta.language, "type": meta.document_type,
                 "territory": meta.territory, "source": meta.source_uri, "visibility": space["visibility"],
                 "roles": space["allowed_roles"], "by": claims.sub},
            ).scalar_one()
        else:
            owned = session.execute(
                text("SELECT 1 FROM document WHERE id = :id AND tenant_id = current_tenant_id() AND deleted_at IS NULL"),
                {"id": document_id},
            ).scalar_one_or_none()
            if owned is None:
                raise HTTPException(404, "document not found in this network")

        existing = session.execute(
            text(
                "SELECT id, document_id, version, status FROM document_version"
                " WHERE document_id = :doc AND content_sha256 = :sha AND pipeline_version = :pipeline"
            ),
            {"doc": document_id, "sha": digest, "pipeline": PIPELINE_VERSION},
        ).mappings().one_or_none()
        if existing is not None:
            return dict(existing), None  # idempotent: same bytes, same pipeline

        version = session.execute(
            text("SELECT coalesce(max(version), 0) + 1 FROM document_version WHERE document_id = :doc"), {"doc": document_id}
        ).scalar_one()
        key = storage.put(session, "documents", f"{document_id}-v{version}.pdf", data, "application/pdf")
        version_id = session.execute(
            text(
                "INSERT INTO document_version (document_id, version, content_sha256, pipeline_version, object_key,"
                " size_bytes, page_count) VALUES (:doc, :version, :sha, :pipeline, :key, :size, :pages) RETURNING id"
            ),
            {"doc": document_id, "version": version, "sha": digest, "pipeline": PIPELINE_VERSION, "key": key,
             "size": len(data), "pages": pages},
        ).scalar_one()
    job = {"id": version_id, "document_id": document_id, "version": version, "status": "uploaded"}
    message = {"type": "ingest", "tenant_id": str(claims.tenant_id), "version_id": str(version_id), "correlation_id": correlation_id}
    return job, message


def process(tenant_id: uuid.UUID, version_id: uuid.UUID) -> str:
    """Runs one ingestion job. Safe under at-least-once delivery: the lease fences writers."""
    with tenant_transaction(tenant_id, SYSTEM_ROLE) as session:
        claimed = session.execute(
            text(
                "UPDATE document_version v SET status = 'processing', lease_until = now() + :lease"
                " FROM document d WHERE v.id = :id AND d.id = v.document_id"
                " AND (v.status = 'uploaded' OR (v.status = 'processing' AND v.lease_until < now()))"
                " RETURNING v.document_id, v.version, v.object_key, v.lease_until, d.title, d.language,"
                " d.space_id, d.visibility, d.allowed_roles"
            ),
            {"id": version_id, "lease": LEASE},
        ).mappings().one_or_none()
        if claimed is None:
            return "not_claimable"

    verdict = _scan_verdict(claimed["object_key"])
    if verdict == "pending":
        _release(version_id, tenant_id, claimed["lease_until"])
        ingestions.add(1, {"outcome": "scan_pending"})
        return "scan_pending"
    if verdict != "clean":
        _finish(tenant_id, version_id, claimed["lease_until"], "failed", {"passed": False}, f"malware_scan:{verdict}")
        ingestions.add(1, {"outcome": "failed"})
        return "failed"
    with tenant_transaction(tenant_id, SYSTEM_ROLE) as session:
        data = storage.read_key(session, claimed["object_key"])

    document = parse(data, claimed["title"], claimed["language"])
    gate = quality(document)
    if not gate["passed"]:
        _finish(tenant_id, version_id, claimed["lease_until"], "failed", gate, f"quality_gate:{gate['reason']}")
        ingestions.add(1, {"outcome": "failed"})
        return "failed"

    chunks = chunk_sections(document.sections, document.language)
    embedder = provider()
    vectors = embedder.embed([c.content for c in chunks])
    with tenant_transaction(tenant_id, SYSTEM_ROLE) as session:
        storage.put(session, "artifacts", f"{claimed['document_id']}-v{claimed['version']}.canonical.json",
                    json.dumps(document.as_dict(), ensure_ascii=False).encode(), "application/json")
        fenced = session.execute(
            text(
                "UPDATE document_version SET status = 'published', published_at = now(), lease_until = NULL,"
                " quality = CAST(:quality AS jsonb) WHERE id = :id AND status = 'processing' AND lease_until = :lease"
            ),
            {"id": version_id, "lease": claimed["lease_until"], "quality": json.dumps(gate | {"chunks": len(chunks)})},
        ).rowcount
        if fenced == 0:
            session.rollback()
            return "fenced"  # the lease expired and another worker owns the job now
        session.execute(
            text(
                "INSERT INTO knowledge_chunk (document_id, version_id, space_id, visibility, allowed_roles, language,"
                " section_path, page_start, page_end, ordinal, content, embedding, embedding_model)"
                " VALUES (:doc, :version, :space, :visibility, :roles, :language, :path, :start, :end, :ordinal,"
                " :content, CAST(:embedding AS vector), :model)"
            ),
            [
                {"doc": claimed["document_id"], "version": version_id, "space": claimed["space_id"],
                 "visibility": claimed["visibility"], "roles": claimed["allowed_roles"], "language": c.language,
                 "path": list(c.section_path), "start": c.page_start, "end": c.page_end, "ordinal": c.ordinal,
                 "content": c.content, "embedding": as_pgvector(v), "model": embedder.model}
                for c, v in zip(chunks, vectors)
            ],
        )
        # Atomic publication: retrieval switches from the old version to the new one at commit.
        session.execute(
            text("UPDATE knowledge_chunk SET active = (version_id = :id) WHERE document_id = :doc AND (active OR version_id = :id)"),
            {"id": version_id, "doc": claimed["document_id"]},
        )
        session.execute(
            text("UPDATE document_version SET status = 'superseded' WHERE document_id = :doc AND status = 'published' AND id <> :id"),
            {"doc": claimed["document_id"], "id": version_id},
        )
        session.execute(
            text("UPDATE document SET active_version = :version WHERE id = :doc"),
            {"version": claimed["version"], "doc": claimed["document_id"]},
        )
    ingestions.add(1, {"outcome": "published"})
    return "published"


def _scan_verdict(key: str) -> str:
    """'clean', 'pending', or the scan status that fails the file closed (threats_found, failed,
    unsupported, access_denied). Without a scanner (local, emulation) every file is clean."""
    if os.environ.get("SECONDCHANCE_MALWARE_SCAN") != "guardduty":
        return "clean"
    deadline = time.monotonic() + SCAN_WAIT.total_seconds()
    while (status := storage.scan_status(key)) is None:
        if time.monotonic() >= deadline:
            return "pending"
        time.sleep(SCAN_POLL_SECONDS)
    return "clean" if status == "NO_THREATS_FOUND" else status.lower()


def _release(version_id: uuid.UUID, tenant_id: uuid.UUID, lease) -> None:
    """Back to 'uploaded': the requeue job sends the message again once the upload is stale."""
    with tenant_transaction(tenant_id, SYSTEM_ROLE) as session:
        session.execute(
            text("UPDATE document_version SET status = 'uploaded', lease_until = NULL"
                 " WHERE id = :id AND status = 'processing' AND lease_until = :lease"),
            {"id": version_id, "lease": lease},
        )


def _finish(tenant_id: uuid.UUID, version_id: uuid.UUID, lease, status: str, gate: dict, error: str) -> None:
    with tenant_transaction(tenant_id, SYSTEM_ROLE) as session:
        session.execute(
            text(
                "UPDATE document_version SET status = :status, error_category = :error, lease_until = NULL,"
                " quality = CAST(:quality AS jsonb) WHERE id = :id AND status = 'processing' AND lease_until = :lease"
            ),
            {"status": status, "error": error, "quality": json.dumps(gate), "id": version_id, "lease": lease},
        )


def delete_document(claims: Claims, document_id: uuid.UUID) -> None:
    """Soft delete: chunks leave retrieval in the same transaction; retention purges later."""
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        updated = session.execute(
            text("UPDATE document SET deleted_at = now() WHERE id = :id AND tenant_id = current_tenant_id() AND deleted_at IS NULL"),
            {"id": document_id},
        ).rowcount
        if not updated:
            raise HTTPException(404, "document not found in this network")
        session.execute(text("UPDATE knowledge_chunk SET active = false WHERE document_id = :id"), {"id": document_id})


def set_space_acl(claims: Claims, space_id: uuid.UUID, allowed_roles: list[str]) -> None:
    """Revocation takes effect on the next query: space, documents and chunks change together."""
    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        updated = session.execute(
            text("UPDATE knowledge_space SET allowed_roles = :roles WHERE id = :id AND tenant_id = current_tenant_id()"),
            {"roles": allowed_roles, "id": space_id},
        ).rowcount
        if not updated:
            raise HTTPException(404, "knowledge space not found in this network")
        for table in ("document", "knowledge_chunk"):
            session.execute(
                text(f"UPDATE {table} SET allowed_roles = :roles WHERE space_id = :id"),  # noqa: S608 - constant table names
                {"roles": allowed_roles, "id": space_id},
            )
