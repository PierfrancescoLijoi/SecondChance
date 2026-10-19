import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from secondchance.identity import Claims, current_claims, require_roles, tenant_session
from secondchance.observability import current_correlation_id, meter
from secondchance.offers import create_offer, list_offers, reserve_offer

router = APIRouter(tags=["offers"])

# scope="function": commit before the response leaves, so a failed commit is a 500,
# never a 200 for data that was not saved.
TenantSession = Depends(tenant_session, scope="function")
reservations_counter = meter.create_counter("secondchance.offers.reservations", description="Reservation attempts by outcome")


class Offer(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    category: str
    quantity: Decimal
    unit: str
    date_kind: Literal["use_by", "best_before"]
    expires_on: date
    storage: str
    status: str
    version: int


class OfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["dairy", "meat_fish", "fruit_vegetables", "bakery", "dry_goods", "frozen", "ready_meals", "beverages", "other"]
    quantity: Decimal = Field(gt=0, le=100_000, max_digits=12, decimal_places=3)
    unit: Literal["kg", "l", "pcs"]
    date_kind: Literal["use_by", "best_before"]
    expires_on: date
    storage: Literal["ambient", "chilled", "frozen"]
    pickup_from: datetime
    pickup_until: datetime

    @model_validator(mode="after")
    def coherent(self) -> "OfferCreate":
        # Cheap domain checks before any query (ADR-016). Country rules (FR-017) come in P1.
        if self.pickup_from.tzinfo is None or self.pickup_until.tzinfo is None:
            raise ValueError("pickup times need a timezone")
        if self.pickup_until <= self.pickup_from:
            raise ValueError("pickup_until must be after pickup_from")
        if self.pickup_until - self.pickup_from > timedelta(days=14):
            raise ValueError("pickup window longer than 14 days")
        if self.date_kind == "use_by" and self.expires_on < date.today():
            raise ValueError("use_by products past their date cannot be offered")
        return self


class OfferCreated(BaseModel):
    id: uuid.UUID
    status: Literal["available"]


class ReserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class ReserveResponse(BaseModel):
    id: uuid.UUID
    status: Literal["reserved"]
    version: int


@router.get("/offers", response_model=list[Offer])
def get_offers(session: Session = TenantSession, claims: Claims = Depends(current_claims)) -> list[dict]:
    return list_offers(session, donor_id=claims.organization_id if claims.role == "donor" else None)


@router.post("/offers", response_model=OfferCreated, status_code=201)
def post_offer(
    body: OfferCreate, session: Session = TenantSession, claims: Claims = Depends(require_roles("donor"))
) -> OfferCreated:
    offer_id = create_offer(session, claims, body.model_dump(), current_correlation_id())
    return OfferCreated(id=offer_id, status="available")


@router.post("/offers/{offer_id}/reserve", response_model=ReserveResponse)
def post_reserve(
    offer_id: uuid.UUID,
    body: ReserveRequest,
    session: Session = TenantSession,
    claims: Claims = Depends(require_roles("coordinator", "org_admin")),
) -> ReserveResponse:
    new_version = reserve_offer(session, offer_id, body.version, claims, current_correlation_id())
    reservations_counter.add(1, {"outcome": "reserved" if new_version else "conflict"})
    if new_version is None:
        raise HTTPException(409, "offer changed or is not available")
    return ReserveResponse(id=offer_id, status="reserved", version=new_version)
