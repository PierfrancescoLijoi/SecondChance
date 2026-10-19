"""Receiving centres and pickup locations (FR-003, FR-014)."""

import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from secondchance import centers
from secondchance.identity import Claims, require_roles, tenant_session
from secondchance.logistics import CATEGORIES, STORAGE
from secondchance.missions import list_missions
from secondchance.observability import current_correlation_id
from secondchance.routes.missions import MissionView

router = APIRouter(tags=["centres"])
TenantSession = Depends(tenant_session, scope="function")

Category = Literal[CATEGORIES]  # type: ignore[valid-type]
Storage = Literal[STORAGE]  # type: ignore[valid-type]


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekday: int = Field(ge=1, le=7)
    opens: time
    closes: time

    @model_validator(mode="after")
    def ordered(self) -> "Slot":
        if self.closes <= self.opens:
            raise ValueError("closes must be after opens")
        return self


class CenterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    status: Literal["active", "paused"] = "active"
    address: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+)*$")
    accepted_categories: list[Category] = Field(min_length=1, max_length=len(CATEGORIES))
    storage_capabilities: list[Storage] = Field(min_length=1, max_length=len(STORAGE))
    daily_capacity_kg: Decimal = Field(gt=0, le=1_000_000, max_digits=10, decimal_places=2)

    @model_validator(mode="after")
    def coherent(self) -> "CenterConfig":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude go together")
        if len(set(self.accepted_categories)) != len(self.accepted_categories) or len(
            set(self.storage_capabilities)
        ) != len(self.storage_capabilities):
            raise ValueError("categories and storage must not repeat")
        return self


class CenterUpdate(CenterConfig):
    version: int = Field(ge=1)


class SlotsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    slots: list[Slot] = Field(max_length=28)

    @model_validator(mode="after")
    def no_overlap(self) -> "SlotsUpdate":
        by_day: dict[int, list[Slot]] = {}
        for slot in self.slots:
            by_day.setdefault(slot.weekday, []).append(slot)
        for slots in by_day.values():
            ordered = sorted(slots, key=lambda s: s.opens)
            if any(later.opens < earlier.closes for earlier, later in zip(ordered, ordered[1:])):
                raise ValueError("slots of the same day must not overlap")
        return self


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CenterView(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    address: str | None
    latitude: float | None
    longitude: float | None
    timezone: str
    accepted_categories: list[str]
    storage_capabilities: list[str]
    daily_capacity_kg: Decimal
    committed_today_kg: Decimal
    version: int
    updated_at: datetime
    slots: list[Slot]


class Versioned(BaseModel):
    id: uuid.UUID
    version: int


def _allowed(claims: Claims, center_id: uuid.UUID) -> None:
    if not centers.may_manage(claims, center_id):
        raise HTTPException(403, "you may manage only your own centre")


@router.get("/centers", response_model=list[CenterView])
def get_centers(
    session: Session = TenantSession,
    claims: Claims = Depends(require_roles("coordinator", "org_admin", "center_staff")),
) -> list[dict]:
    if claims.role == "center_staff":
        return centers.list_centers(session, only=claims.center_id) if claims.center_id else []
    return centers.list_centers(session)


@router.get("/centers/{center_id}", response_model=CenterView)
def get_center(
    center_id: uuid.UUID,
    session: Session = TenantSession,
    claims: Claims = Depends(require_roles("coordinator", "org_admin", "center_staff")),
) -> dict:
    if claims.role == "center_staff":
        _allowed(claims, center_id)
    found = centers.list_centers(session, only=center_id)
    if not found:
        raise HTTPException(404, "centre not found")
    return found[0]


@router.post("/centers", response_model=Versioned, status_code=201)
def post_center(
    body: CenterConfig, session: Session = TenantSession, claims: Claims = Depends(require_roles("org_admin"))
) -> Versioned:
    center_id = centers.create_center(session, claims, body.model_dump(), current_correlation_id())
    return Versioned(id=center_id, version=1)


@router.post("/centers/{center_id}", response_model=Versioned)
def post_center_update(
    center_id: uuid.UUID,
    body: CenterUpdate,
    session: Session = TenantSession,
    claims: Claims = Depends(require_roles("org_admin", "center_staff")),
) -> Versioned:
    _allowed(claims, center_id)
    version = centers.update_center(session, claims, center_id, body.model_dump(), current_correlation_id())
    return Versioned(id=center_id, version=version)


@router.post("/centers/{center_id}/slots", response_model=Versioned)
def post_center_slots(
    center_id: uuid.UUID,
    body: SlotsUpdate,
    session: Session = TenantSession,
    claims: Claims = Depends(require_roles("org_admin", "center_staff")),
) -> Versioned:
    _allowed(claims, center_id)
    slots = [slot.model_dump() for slot in body.slots]
    version = centers.replace_slots(session, claims, center_id, body.version, slots, current_correlation_id())
    return Versioned(id=center_id, version=version)


@router.get("/centers/{center_id}/deliveries", response_model=list[MissionView])
def get_center_deliveries(
    center_id: uuid.UUID,
    session: Session = TenantSession,
    claims: Claims = Depends(require_roles("coordinator", "org_admin", "center_staff")),
) -> list[dict]:
    if claims.role == "center_staff":
        _allowed(claims, center_id)
    return list_missions(session, claims, center_id=center_id)


@router.post("/organizations/{organization_id}/location", status_code=204)
def post_organization_location(
    organization_id: uuid.UUID,
    body: Location,
    session: Session = TenantSession,
    claims: Claims = Depends(require_roles("donor", "org_admin")),
) -> None:
    centers.set_organization_location(session, claims, organization_id, body.latitude, body.longitude,
                                      current_correlation_id())
