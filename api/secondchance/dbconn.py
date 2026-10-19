"""Engines for every database role, with IAM authentication on Aurora (ADR-006, ADR-018).

With SECONDCHANCE_DB_IAM_AUTH=1 each new connection gets a short-lived token instead of a
password; the function's IAM role needs rds-db:connect for that database user only.
"""

import os

from sqlalchemy import Engine, create_engine, event


def make_engine(url: str, **kwargs) -> Engine:
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

    return engine
