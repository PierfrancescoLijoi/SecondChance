from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from secondchance.experiments import assign
from secondchance.identity import Claims, current_claims, tenant_session
from secondchance.observability import current_correlation_id

router = APIRouter(tags=["experiments"])


class Assignment(BaseModel):
    experiment: str
    variant: str


@router.get("/experiments/{key}/assignment", response_model=Assignment)
def get_assignment(
    key: str,
    session: Session = Depends(tenant_session, scope="function"),
    claims: Claims = Depends(current_claims),
) -> Assignment:
    variant = assign(session, key, claims, current_correlation_id())
    if variant is None:
        raise HTTPException(404, "experiment not found")
    return Assignment(experiment=key, variant=variant)
