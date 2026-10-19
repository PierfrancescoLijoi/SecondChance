FROM python:3.12.14-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH=/opt/venv/bin:$PATH
WORKDIR /gateway
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY mcp_gateway ./mcp_gateway
USER nobody

FROM base AS worker
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["mcp_gateway.lambda_handler.gateway"]

FROM base AS service
EXPOSE 8010
CMD ["uvicorn", "mcp_gateway.app:app", "--host", "0.0.0.0", "--port", "8010"]
