"""Container Apps Job entry points (ADR-023): `python -m secondchance.azure_entry <task> [options]`.

The Azure counterpart of secondchance.aws_lambda for work that is not a queue consumer:

  bootstrap   as the server's Entra administrator: database roles for the managed identities, extensions, ownership
  migrate     as secondchance_migrator: Alembic, the demo seed, the first platform administrator
  retention   nightly purge (secondchance_maintenance)
  requeue     lost messages, expired leases, undelivered e-mail, expired offers
  seed        synthetic knowledge through Blob Storage and the embedding deployment (demo only)
  check       acceptance probe of the private data and AI paths (what scripts/azure/verify.sh reads)
  ping        puts one unprocessable message on the notify queue: a live consumer drops it, which proves the worker
              scaled up from zero and the broker, the identity and the queue are wired (scripts/azure/verify.sh)
  tools       demo only: one knowledge_search through the MCP gateway, as an MCP client of the synthetic Italian network

Each task prints one JSON line on stdout and exits non-zero on failure, so a job execution's status is the verdict.
Queue consumers are plain long-running containers: python -m secondchance.jobs | secondchance.notify | secondchance.agents.worker.
"""

import argparse
import json
import logging
import os
import sys
import uuid

from secondchance.observability import configure_logging

log = logging.getLogger(__name__)

DATABASE = "secondchance"
ENTRA_DATABASE_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
# SECONDCHANCE_DB_PRINCIPALS is {"secondchance_app": "<object id>", ...}, written by Terraform from the identities it created.
ROLES = ("secondchance_migrator", "secondchance_app", "secondchance_maintenance")

ROLE_SQL = """
ALTER ROLE secondchance_app SET statement_timeout = '10s';
ALTER ROLE secondchance_app SET lock_timeout = '5s';
ALTER ROLE secondchance_app SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE secondchance_maintenance SET statement_timeout = '60s';
GRANT secondchance_migrator TO CURRENT_USER;
"""
DATABASE_SQL = """
REVOKE TEMPORARY ON DATABASE secondchance FROM PUBLIC;
"""
EXTENSION_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
"""


def bootstrap() -> dict:
    """Idempotent. Roles are created from the managed identities' object ids, so no password ever exists."""
    import psycopg

    from secondchance.cloud import bearer

    principals = json.loads(os.environ["SECONDCHANCE_DB_PRINCIPALS"])
    if set(principals) != set(ROLES):
        raise RuntimeError(f"SECONDCHANCE_DB_PRINCIPALS must name exactly {sorted(ROLES)}")
    for object_id in principals.values():
        uuid.UUID(object_id)  # these values go into SQL below as literals only after this check

    def connect(database: str):
        return psycopg.connect(
            host=os.environ["SECONDCHANCE_DB_HOST"], dbname=database, user=os.environ["SECONDCHANCE_DB_ADMIN_USER"],
            password=bearer(ENTRA_DATABASE_SCOPE), sslmode="require", autocommit=True,  # CREATE DATABASE cannot run in a transaction
        )

    with connect("postgres") as connection:
        for role, object_id in principals.items():
            exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if exists is None:
                connection.execute(
                    "SELECT pg_catalog.pgaadauth_create_principal_with_oid(%s, %s, 'service', false, false)",
                    (role, object_id),
                )
        connection.execute(ROLE_SQL)
        # Created here, not by Terraform, so that the schema owner is the migrator from the first moment
        # (the owner of a database made through the Azure API is a platform role we may not be able to change).
        if connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone() is None:
            connection.execute(f"CREATE DATABASE {DATABASE} OWNER secondchance_migrator")  # noqa: S608 - a module constant
        else:
            connection.execute(f"ALTER DATABASE {DATABASE} OWNER TO secondchance_migrator")  # noqa: S608
        connection.execute(DATABASE_SQL)
    with connect(DATABASE) as connection:  # extensions belong to one database
        connection.execute(EXTENSION_SQL)
    return {"bootstrap": "done", "roles": sorted(principals)}


def migrate(seed: bool, platform_admin: str | None) -> dict:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from secondchance.dbconn import make_engine

    result: dict = {}
    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini")), "head")
    result["migrations"] = "head"
    if seed and os.environ.get("SECONDCHANCE_ENV") == "demo":
        from secondchance.seed import seed as load_seed

        load_seed()
        result["seed"] = "synthetic"
    if platform_admin:
        from secondchance.seed import TENANT_PLATFORM

        uuid.UUID(platform_admin)  # an Entra object id, never free text
        with make_engine(os.environ["SECONDCHANCE_MIGRATOR_URL"]).begin() as connection:
            connection.execute(
                text("INSERT INTO tenant (id, name, country, kind, status) VALUES (:id, 'SecondChance platform', 'EU', 'platform', 'active')"
                     " ON CONFLICT (id) DO NOTHING"),
                {"id": TENANT_PLATFORM},
            )
            connection.execute(
                text("INSERT INTO membership (id, subject, tenant_id, role, status) VALUES (:id, :sub, :tenant, 'platform_admin', 'active')"
                     " ON CONFLICT (subject, tenant_id) DO UPDATE SET role = 'platform_admin', status = 'active'"),
                {"id": uuid.uuid4(), "sub": platform_admin, "tenant": TENANT_PLATFORM},
            )
        result["platform_admin"] = "granted"
    return result



def tools() -> dict:
    """The same smoke test scripts/verify-aws.sh runs against the gateway, from inside the private network."""
    if os.environ.get("SECONDCHANCE_ENV") != "demo":
        raise RuntimeError("the tool smoke test reads the synthetic demo tenant")
    from secondchance.seed import TENANT_IT  # the synthetic Italian network
    from secondchance.tools.client import ToolGatewayClient, ToolInvocation

    result = ToolGatewayClient.from_environment().call(ToolInvocation(
        name="knowledge_search", arguments={"query": "temperatura alimenti refrigerati", "language": "it", "top_k": 3},
        tenant_id=str(TENANT_IT), subject="demo-it-coordinator", role="coordinator", agent="mcp_client",
        correlation_id="azure-deploy-smoke",
    ))
    hits = result.get("hits", [])
    if not hits:
        raise RuntimeError("MCP/RAG smoke test returned no authorised evidence")
    return {"hits": len(hits)}


def ping() -> dict:
    from secondchance.queues import open_queue

    open_queue("SECONDCHANCE_QUEUE_NOTIFY", "notify").send({"type": "verify", "note": "deployment check; safe to drop"})
    return {"sent": "notify"}


def run(task: str, options: argparse.Namespace) -> dict:
    if task == "bootstrap":
        return bootstrap()
    if task == "tools":
        return tools()
    if task == "ping":
        return ping()
    if task == "migrate":
        return migrate(options.seed, options.platform_admin or os.environ.get("SECONDCHANCE_PLATFORM_ADMIN_SUB"))
    # The handlers below are provider-neutral: their queues, models and stores come from the adapters.
    from secondchance import aws_lambda

    handlers = {"retention": aws_lambda.retention, "requeue": aws_lambda.requeue,
                "seed": aws_lambda.demo_seed, "check": aws_lambda.runtime_check}
    return handlers[task]({}, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secondchance.azure_entry")
    parser.add_argument("task", choices=["bootstrap", "migrate", "retention", "requeue", "seed", "check", "ping", "tools"])
    parser.add_argument("--no-seed", dest="seed", action="store_false", help="migrate: skip the synthetic demo data")
    parser.add_argument("--platform-admin", help="migrate: object id of the first platform administrator")
    options = parser.parse_args(argv)
    configure_logging()
    try:
        result = run(options.task, options)
    except Exception:
        log.exception("task %s failed", options.task)
        return 1
    print(json.dumps({"task": options.task, **result}, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
