import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Claims:
    """The resolved principal: who, in which tenant, with which role (ADR-017).

    Built only from a membership row (secondchance.identity) or from a run's stored identity
    (agents worker); never from token claims or model output.
    """

    sub: str
    tenant_id: uuid.UUID
    role: str
    organization_id: uuid.UUID | None = None
    center_id: uuid.UUID | None = None  # centre staff only, assigned by an admin
