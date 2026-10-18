"""Fail fast (ADR-016): reject early and cheaply, before databases, models or solvers.

Order of the application-side stages: body size (middleware, no I/O) -> strict schemas
(Pydantic, no I/O) -> membership and role (one indexed query) -> quotas (one aggregate
query) -> work. Every rejection is counted by stage and reason.
"""

import os

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from secondchance.observability import meter


def _limit(name: str, default: int) -> int:
    return int(os.environ.get(f"SECONDCHANCE_LIMIT_{name.upper()}", default))


LIMITS = {
    "agent_runs_concurrent": _limit("agent_runs_concurrent", 5),
    "agent_runs_daily": _limit("agent_runs_daily", 200),
    "uploads_daily": _limit("uploads_daily", 50),
    "registrations_per_subject": _limit("registrations_per_subject", 3),
    "body_bytes": _limit("body_bytes", 64 * 1024),
    "upload_bytes": _limit("upload_bytes", 20 * 1024 * 1024),
    "pdf_pages": _limit("pdf_pages", 60),
}
UPLOAD_PATHS = ("/documents",)

rejections = meter.create_counter("secondchance.admission.rejections", description="Requests rejected early, by stage and reason")


def reject(stage: str, reason: str, status: int = 429, retry_after: int | None = None) -> HTTPException:
    rejections.add(1, {"stage": stage, "reason": reason})
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return HTTPException(status, reason, headers=headers)


def admit_agent_run(session: Session) -> None:
    """Per-tenant concurrency and daily quota; RLS scopes the counts to the caller's tenant."""
    active, today = session.execute(
        text(
            "SELECT count(*) FILTER (WHERE status IN ('queued', 'running')),"
            " count(*) FILTER (WHERE created_at > now() - interval '1 day')"
            " FROM agent_run"
        )
    ).one()
    if active >= LIMITS["agent_runs_concurrent"]:
        raise reject("quota", "too many agent runs in progress for this network", retry_after=30)
    if today >= LIMITS["agent_runs_daily"]:
        raise reject("quota", "daily agent run quota reached for this network", retry_after=3600)


def admit_upload(session: Session) -> None:
    today = session.execute(
        text("SELECT count(*) FROM document_version WHERE created_at > now() - interval '1 day'")
    ).scalar_one()
    if today >= LIMITS["uploads_daily"]:
        raise reject("quota", "daily upload quota reached for this network", retry_after=3600)


class BodySizeLimitMiddleware:
    """413 before the body is read: from Content-Length, or while streaming when it is absent."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_upload = scope["path"].startswith(UPLOAD_PATHS)
        limit = LIMITS["upload_bytes"] if is_upload else LIMITS["body_bytes"]
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            await self._too_large(send)
            return

        received = 0

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, counting_receive, send)
        except _BodyTooLarge:
            await self._too_large(send)

    @staticmethod
    async def _too_large(send) -> None:
        rejections.add(1, {"stage": "body", "reason": "too_large"})
        body = b'{"detail":"request body too large"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass
