# One Dockerfile for the local stack and the Lambda images (ADR-001, ADR-018).
#   worker:     SQS and scheduled handlers through awslambdaric (command chosen per function)
#   lambda-api: the API behind the Lambda Web Adapter; scripts/deploy.sh pushes it as <tag>-api
#   api:        the API on uvicorn, the default target that Compose builds; it never pulls the adapter
FROM python:3.12.14-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY secondchance ./secondchance
USER nobody

FROM base AS worker
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["secondchance.aws_lambda.jobs"]

FROM base AS http
EXPOSE 8000
CMD ["uvicorn", "secondchance.main:app", "--host", "0.0.0.0", "--port", "8000"]

# The adapter turns Lambda invocations into HTTP requests for uvicorn; outside Lambda it stays inert.
FROM http AS lambda-api
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter
ENV AWS_LWA_PORT=8000 \
    AWS_LWA_READINESS_CHECK_PATH=/health

FROM http AS api
