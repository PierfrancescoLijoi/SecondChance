"""In-app notifications (FR-026) and the operational dashboard (FR-052, FR-053)."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from secondchance import dashboard, notifications
from secondchance.identity import Claims, MANAGERS, current_claims, require_roles, tenant_session

router = APIRouter(tags=["operations"])
TenantSession = Depends(tenant_session, scope="function")


class Notification(BaseModel):
    id: uuid.UUID
    kind: str
    object_type: Literal["mission", "matching_run", "allocation_proposal"]
    object_id: uuid.UUID
    created_at: datetime
    read_at: datetime | None


class Inbox(BaseModel):
    unread: int
    items: list[Notification]


class Marked(BaseModel):
    marked: int


@router.get("/notifications", response_model=Inbox)
def get_notifications(
    unread: bool = False, session: Session = TenantSession, _: Claims = Depends(current_claims)
) -> Inbox:
    items, count = notifications.inbox(session, unread_only=unread)
    return Inbox(unread=count, items=[Notification(**item) for item in items])


@router.post("/notifications/read-all", response_model=Marked)
def post_read_all(session: Session = TenantSession, _: Claims = Depends(current_claims)) -> Marked:
    return Marked(marked=notifications.mark_read(session, None))


@router.post("/notifications/{notification_id}/read", response_model=Marked)
def post_read(
    notification_id: uuid.UUID, session: Session = TenantSession, _: Claims = Depends(current_claims)
) -> Marked:
    marked = notifications.mark_read(session, notification_id)
    if marked == 0:
        raise HTTPException(404, "notification not found or already read")
    return Marked(marked=marked)


@router.get("/dashboard")
def get_dashboard(
    days: int = Query(default=30, ge=1, le=365),
    session: Session = TenantSession,
    _: Claims = Depends(require_roles(*MANAGERS)),
) -> dict:
    return dashboard.summary(session, days)
