"""Origin lock for the Azure edge (ADR-023): only Front Door may reach the public Container App.

Container Apps cannot filter by the AzureFrontDoor.Backend service tag, so the profile's id travels in
X-Azure-FDID and is checked here. The WAF, the rate limit and the security headers live in Front Door;
a request that skipped it answers 403 before any route, token check or database access.
"""

import hmac

from starlette.responses import JSONResponse

HEADER = b"x-azure-fdid"
OPEN_PATHS = frozenset({"/health"})  # the platform probes and the Front Door probe carry no profile id


class FrontDoorOnly:
    def __init__(self, app, front_door_id: str) -> None:
        if not front_door_id:
            raise ValueError("front_door_id is required")
        self.app = app
        self.front_door_id = front_door_id

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"] not in OPEN_PATHS:
            presented = dict(scope["headers"]).get(HEADER, b"").decode("latin-1")
            if not hmac.compare_digest(presented, self.front_door_id):
                await JSONResponse({"detail": "request did not come through the edge"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
