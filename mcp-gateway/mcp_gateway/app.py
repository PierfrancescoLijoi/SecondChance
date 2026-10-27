from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from mcp_gateway.service import handle, policy
from mcp_gateway.service_auth import require_service_role

app = FastAPI(title="SecondChance MCP Tool Gateway", version="1.0.0")


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict = Field(default_factory=dict)
    context: dict


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/tools/catalog", dependencies=[Depends(require_service_role("Tool.Invoke"))])
def catalog() -> list[dict]:
    return policy.catalog()


@app.post("/v1/tools/call", dependencies=[Depends(require_service_role("Tool.Invoke"))])
def call(body: ToolCall) -> dict:
    result = handle(body.model_dump())
    if "error" in result:
        raise HTTPException(result["status_code"], result["error"])
    return result
