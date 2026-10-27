"""AWS Lambda entry points (ADR-001, ADR-018). Same image as Compose.

The API runs uvicorn behind the Lambda Web Adapter. These handlers run through
awslambdaric, selected per function by Terraform (image_config.command):
  python -m awslambdaric secondchance.aws_lambda.<handler>
"""

import json
import logging
import os
import uuid
from functools import lru_cache

from secondchance.dbconn import make_engine
from secondchance.observability import configure_logging
from secondchance.queues import MalformedMessage, Queue, open_queue

configure_logging()
log = logging.getLogger(__name__)


@lru_cache
def _queue(env_name: str, default: str) -> Queue:
    return open_queue(env_name, default)


def _batch(event: dict, handle) -> dict:
    """SQS partial batch response: only failed records return to the queue (and later the DLQ)."""
    failures = []
    for record in event.get("Records", []):
        try:
            handle(json.loads(record["body"]))
        except (MalformedMessage, json.JSONDecodeError) as error:
            log.warning("malformed message %s dropped: %s", record.get("messageId"), error)
        except Exception:
            log.exception("message %s failed", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def agents(event: dict, context) -> dict:
    from secondchance.agents.worker import handle

    queue = _queue("SECONDCHANCE_QUEUE_AGENTS", "agents")
    return _batch(event, lambda body: handle(body, queue))


def agent_step(event: dict, context) -> dict:
    """Execute one bounded agent step; Step Functions owns the durable run loop."""
    from secondchance.agents.builtin import AGENTS
    from secondchance.agents.runtime import execute, workflow_resume
    from secondchance.queues import MemoryQueue, require

    message = require(event, "tenant_id", "run_id", "seq", "correlation_id")
    outcome = execute(message, AGENTS, MemoryQueue(), dispatch_next=False)
    if outcome == "not_claimable":
        resume = workflow_resume(uuid.UUID(message["tenant_id"]), uuid.UUID(message["run_id"]), int(message["seq"]))
        if resume == "advance":
            outcome = "continue"
        elif resume == "wait":
            return {**message, "continue": False, "retry": True, "outcome": "waiting_for_lease"}
    return {
        **message,
        "seq": int(message["seq"]) + 1 if outcome == "continue" else int(message["seq"]),
        "continue": outcome == "continue",
        "retry": False,
        "outcome": outcome,
    }


def realtime_authorizer(event: dict, context) -> dict:
    from secondchance.realtime import websocket_authorizer

    return websocket_authorizer(event, context)


def realtime(event: dict, context) -> dict:
    from secondchance.realtime import websocket_handler

    return websocket_handler(event, context)


def realtime_publisher(event: dict, context) -> dict:
    """Relay private runtime events to the public WebSocket management endpoint."""
    from secondchance.realtime import RealtimePublisher

    publisher = RealtimePublisher.from_environment()

    def publish(message: dict) -> None:
        publisher.publish(str(message["run_id"]), message["event"])

    return _batch(event, publish)


def jobs(event: dict, context) -> dict:
    from secondchance.jobs import handle

    return _batch(event, handle)


def notifier(event: dict, context) -> dict:
    """Email delivery for the `notify` queue (FR-026). Public (no VPC) and without data permissions:
    it resolves the address in Cognito and sends through SES."""
    from secondchance.notify import process

    return _batch(event, process)


def tool_executor(event: dict, context) -> dict:
    """Private domain-tool executor. Only the gateway Lambda may invoke it in AWS."""
    from sqlalchemy import text

    from secondchance.db import tenant_transaction
    from secondchance.tools.builtin import GATEWAY
    from secondchance.tools.gateway import ToolContext

    identity = event["context"]
    tenant_id = uuid.UUID(identity["tenant_id"])
    role, subject, agent = identity["role"], identity["subject"], identity["agent"]
    with tenant_transaction(tenant_id, "agent_worker", subject) as session:
        if agent != "mcp_client":
            verified = session.execute(
                text(
                    "SELECT r.requested_by, r.requested_role, s.agent FROM agent_run r"
                    " JOIN agent_step s ON s.run_id = r.id"
                    " WHERE r.id = :run AND s.seq = :seq AND s.status = 'running'"
                ),
                {"run": uuid.UUID(identity["run_id"]), "seq": int(identity["seq"])},
            ).mappings().one_or_none()
            if verified is None or verified["agent"] != agent:
                raise PermissionError("tool caller is not the active run step")
            subject, role = verified["requested_by"], verified["requested_role"]
        session.execute(
            text("SELECT set_config('app.role', :role, true), set_config('app.subject', :subject, true)"),
            {"role": role, "subject": subject},
        )
        tool_context = ToolContext(
            session=session, tenant_id=tenant_id, subject=subject,
            role=role, agent=agent,
            correlation_id=identity["correlation_id"],
        )
        return GATEWAY.call(event["name"], event.get("arguments", {}), tool_context)


def demo_seed(event: dict, context) -> dict:
    """Load synthetic documents through S3, Bedrock embeddings and the production ingestion path."""
    if os.environ.get("SECONDCHANCE_ENV") != "demo":
        raise RuntimeError("synthetic knowledge is allowed only in the demo environment")
    from secondchance.knowledge.sample import load_demo_documents

    outcomes = load_demo_documents()
    if not outcomes or any(outcome != "published" for outcome in outcomes):
        raise RuntimeError(f"demo knowledge ingestion incomplete: {outcomes}")
    return {"documents": len(outcomes), "outcomes": outcomes}


def runtime_check(event: dict, context) -> dict:
    """Acceptance probe for the deployed private data and AI paths.

    Unlike the public health endpoint, this function uses the same VPC, IAM role,
    endpoints and environment as an agent worker. It is invoked only by the deploy
    verifier, has no event source, and does not modify domain data.
    """
    import math

    from sqlalchemy import text

    from secondchance.db import engine
    from secondchance.knowledge.embeddings import DIMENSIONS, provider
    from secondchance.llm import guardrail, model
    from secondchance.routing import configured_router

    with engine.connect() as connection:
        if connection.execute(text("SELECT 1")).scalar_one() != 1:
            raise RuntimeError("Aurora connectivity check failed")

    embedder = provider()
    vectors = embedder.embed(["SecondChance AWS runtime acceptance check"])
    if len(vectors) != 1 or len(vectors[0]) != DIMENSIONS or not all(math.isfinite(value) for value in vectors[0]):
        raise RuntimeError("Bedrock embedding check returned an invalid vector")

    language_model = model()
    if language_model is None:
        raise RuntimeError("production language model is not configured")
    completion = language_model.complete(
        "This is a deployment health check. Reply with the single word OK.",
        "Confirm that the model invocation works.",
    )
    if completion.refused or not completion.text.strip().upper().startswith("OK"):
        raise RuntimeError("Bedrock Converse check did not return OK")

    # The same ApplyGuardrail call that wraps every RAG answer: proves IAM and the published version.
    guard = guardrail()
    if guard is None:
        raise RuntimeError("Bedrock guardrail is not configured")
    if guard.blocks_question("At which temperature must refrigerated food be kept?"):
        raise RuntimeError("Bedrock guardrail blocked a benign question")

    from secondchance.matching import self_check

    solver = self_check()  # OR-Tools' native library inside the read-only Lambda sandbox

    decision = configured_router().route("Pianifica il ritiro e coordina la consegna della donazione")
    if decision.outcome != "ok" or decision.intent != "MULTI_AGENT_TASK":
        raise RuntimeError(
            f"hybrid router check failed: router={decision.router}, outcome={decision.outcome}, intent={decision.intent}"
        )
    return {
        "database": "ok",
        "model": language_model.model_id,
        "guardrail": "ok",
        "embedding_model": embedder.model,
        "embedding_dimensions": len(vectors[0]),
        "router": decision.router,
        "router_intent": decision.intent,
        "solver": solver,
    }


def retention(event: dict, context) -> dict:
    from secondchance.retention import purge

    with make_engine(os.environ["SECONDCHANCE_MAINTENANCE_URL"]).begin() as connection:
        deleted = purge(connection)
    log.info("retention: %s", deleted)
    return deleted


def requeue(event: dict, context) -> dict:
    """Recovery every few minutes: lost messages, expired leases, undelivered emails, expired offers."""
    from secondchance.agents.dispatch import configured_dispatcher
    from secondchance.agents.runtime import requeue_stale as requeue_steps
    from secondchance.jobs import requeue_stale as requeue_ingestion
    from secondchance.matching import requeue_stale as requeue_matching
    from secondchance.notifications import requeue_pending
    from secondchance.offers import expire_stale

    engine = make_engine(os.environ["SECONDCHANCE_MAINTENANCE_URL"])
    jobs_queue = _queue("SECONDCHANCE_QUEUE_JOBS", "jobs")
    with engine.connect() as connection:
        steps = requeue_steps(connection, configured_dispatcher(recover=True))
        ingestion = requeue_ingestion(connection, jobs_queue)
        matching = requeue_matching(connection, jobs_queue)
    with engine.begin() as connection:  # these two write: one transaction each run
        emails = requeue_pending(connection, _queue("SECONDCHANCE_QUEUE_NOTIFY", "notify"))
        expired = expire_stale(connection)
    return {"agent_steps": steps, "ingestion_jobs": ingestion, "matching_runs": matching,
            "notification_emails": emails, "expired_offers": expired}


# --- one-off administration, invoked by scripts/deploy.sh ---

BOOTSTRAP_SQL = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'secondchance_migrator') THEN CREATE ROLE secondchance_migrator LOGIN; END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'secondchance_app') THEN CREATE ROLE secondchance_app LOGIN; END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'secondchance_maintenance') THEN CREATE ROLE secondchance_maintenance LOGIN; END IF;
END $$;
GRANT rds_iam TO secondchance_migrator, secondchance_app, secondchance_maintenance;
ALTER ROLE secondchance_app SET statement_timeout = '10s';
ALTER ROLE secondchance_app SET lock_timeout = '5s';
ALTER ROLE secondchance_app SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE secondchance_maintenance SET statement_timeout = '60s';
GRANT secondchance_migrator TO CURRENT_USER;
ALTER DATABASE secondchance OWNER TO secondchance_migrator;
REVOKE TEMPORARY ON DATABASE secondchance FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
"""


def migrate(event: dict, context) -> dict:
    """Database roles (Aurora master secret, once), Alembic upgrade, optional first platform admin.

    event: {"bootstrap": true} on the first deploy; {"platform_admin_sub": "<Cognito sub>"} to
    grant the first platform admin after that person has signed up.
    """
    import boto3
    import psycopg
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    result: dict = {}
    if event.get("bootstrap"):
        secret = json.loads(
            boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["SECONDCHANCE_DB_MASTER_SECRET_ARN"])["SecretString"]
        )
        with psycopg.connect(host=os.environ["SECONDCHANCE_DB_HOST"], dbname="secondchance", user=secret["username"],
                             password=secret["password"], sslmode="require", autocommit=True) as connection:
            connection.execute(BOOTSTRAP_SQL)
        result["bootstrap"] = "done"

    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini")), "head")
    result["migrations"] = "head"

    if os.environ.get("SECONDCHANCE_ENV") == "demo" and event.get("seed", True):
        from secondchance.seed import seed

        seed()
        result["seed"] = "synthetic"

    subject = event.get("platform_admin_sub")
    if subject:
        from secondchance.seed import TENANT_PLATFORM

        with make_engine(os.environ["SECONDCHANCE_MIGRATOR_URL"]).begin() as connection:
            connection.execute(
                text("INSERT INTO tenant (id, name, country, kind, status) VALUES (:id, 'SecondChance platform', 'EU', 'platform', 'active')"
                     " ON CONFLICT (id) DO NOTHING"),
                {"id": TENANT_PLATFORM},
            )
            connection.execute(
                text("INSERT INTO membership (id, subject, tenant_id, role, status) VALUES (:id, :sub, :tenant, 'platform_admin', 'active')"
                     " ON CONFLICT (subject, tenant_id) DO UPDATE SET role = 'platform_admin', status = 'active'"),
                {"id": uuid.uuid4(), "sub": subject, "tenant": TENANT_PLATFORM},
            )
        result["platform_admin"] = "granted"
    return result
