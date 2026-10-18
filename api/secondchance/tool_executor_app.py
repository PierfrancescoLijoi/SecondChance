"""Private local transport for the domain tool executor; never exposed by the public API."""

from awslambdaric.lambda_runtime_marshaller import to_json
from fastapi import FastAPI, Response

from secondchance.aws_lambda import tool_executor

app = FastAPI(title="SecondChance private tool executor")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/execute")
def execute(payload: dict) -> Response:
    # The Lambda runtime's own encoder: Compose fails exactly where Lambda would (UUID, datetime).
    return Response(to_json(tool_executor(payload, None)), media_type="application/json")
