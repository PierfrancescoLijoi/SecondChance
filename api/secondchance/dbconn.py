"""Engines for every database role, with token authentication instead of passwords (ADR-006, ADR-018, ADR-023).

- SECONDCHANCE_DB_IAM_AUTH=1 (AWS): each new connection gets a short-lived RDS IAM token; the function's
  IAM role needs rds-db:connect for that database user only.
- SECONDCHANCE_DB_ENTRA_AUTH=1 (Azure): the token is a Microsoft Entra access token for the container's
  managed identity, which Terraform mapped to the database role of the same name in the URL.
"""

import os

from sqlalchemy import Engine, create_engine, event

ENTRA_DATABASE_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
# Entra tokens live about an hour and are checked when a connection opens: recycle well before that so
# a pooled connection never outlives the token that opened it by much.
ENTRA_POOL_RECYCLE_SECONDS = 2400


def entra_pool_options() -> dict:
    """Bounded pools are the connection bulkhead that RDS Proxy gave the Lambdas (ADR-006)."""
    return {
        "pool_size": int(os.environ.get("SECONDCHANCE_DB_POOL_SIZE", "4")),
        "max_overflow": int(os.environ.get("SECONDCHANCE_DB_MAX_OVERFLOW", "2")),
        "pool_recycle": ENTRA_POOL_RECYCLE_SECONDS,
    }


def make_engine(url: str, **kwargs) -> Engine:
    entra = os.environ.get("SECONDCHANCE_DB_ENTRA_AUTH") == "1"
    if entra:
        for key, value in entra_pool_options().items():
            kwargs.setdefault(key, value)
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if os.environ.get("SECONDCHANCE_DB_IAM_AUTH") == "1":
        import boto3

        rds = boto3.client("rds", region_name=os.environ.get("AWS_REGION", "eu-central-1"))

        @event.listens_for(engine, "do_connect")
        def _iam_token(dialect, conn_rec, cargs, cparams) -> None:
            cparams["password"] = rds.generate_db_auth_token(
                DBHostname=cparams["host"], Port=int(cparams.get("port", 5432)), DBUsername=cparams["user"]
            )
            cparams["sslmode"] = "require"

    if entra:
        from secondchance.cloud import bearer

        @event.listens_for(engine, "do_connect")
        def _entra_token(dialect, conn_rec, cargs, cparams) -> None:
            cparams["password"] = bearer(ENTRA_DATABASE_SCOPE)
            cparams["sslmode"] = "require"

    return engine
