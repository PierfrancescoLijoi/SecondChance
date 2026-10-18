import os

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from secondchance import auth
from secondchance.admission import BodySizeLimitMiddleware, rejections
from secondchance.db import engine
from secondchance.observability import CorrelationIdMiddleware, configure_logging, configure_telemetry
from secondchance.routes import accounts, agents, assist, experiments, knowledge, offers

configure_logging()
app = FastAPI(title="SecondChance API", version="0.3.0")

# Starlette wraps in reverse: the last one added runs first. Order at runtime:
# correlation ID -> CORS -> body size limit (ADR-016, stage 3) -> routes.
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("SECONDCHANCE_WEB_ORIGINS", "http://localhost:5173").split(",") if o],
    allow_methods=["GET", "POST"],  # writes are POST only: no PUT/PATCH/DELETE to secure
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID", "X-Tenant-ID"],
    expose_headers=["X-Correlation-ID", "Retry-After"],
)
app.add_middleware(CorrelationIdMiddleware)
configure_telemetry(app, engine)

for module in (accounts, offers, agents, knowledge, assist, experiments):
    app.include_router(module.router)
if auth.MODE == "mock":  # local only: secondchance.auth refuses mock mode outside SECONDCHANCE_ENV=local
    from secondchance.routes import dev

    app.include_router(dev.router)


@app.exception_handler(RequestValidationError)
async def count_schema_rejections(request: Request, exc: RequestValidationError):
    rejections.add(1, {"stage": "schema", "reason": "invalid_request"})  # ADR-016, stage 4
    return await request_validation_exception_handler(request, exc)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
