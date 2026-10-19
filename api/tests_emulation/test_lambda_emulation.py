"""The deployed system, function by function, on an emulated AWS (see conftest.py).

What only a Lambda shows: the image entrypoints, awslambdaric's plain-JSON marshalling, a
read-only filesystem, IAM database tokens over TLS, the Aurora master that is not a superuser,
Lambda-to-Lambda Invoke, SQS event records and the Lambda Web Adapter behind API Gateway.
"""

import re
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives.asymmetric import rsa

from secondchance.knowledge.sample import make_pdf
from secondchance.seed import TENANT_IT, _id

API = Path(__file__).resolve().parents[1]
COORDINATOR, ADMIN = "demo-it-coordinator", "demo-it-admin"
MCP_CONTEXT = {"tenant_id": str(TENANT_IT), "subject": COORDINATOR, "role": "coordinator",
               "agent": "mcp_client", "correlation_id": "emulation"}
SEARCH = {"query": "temperatura alimenti refrigerati", "language": "it", "top_k": 3}
TASK = "Un supermercato offre 40 kg di yogurt refrigerato da donare domani"
WEBSOCKET_CONNECT = "arn:aws:execute-api:eu-central-1:123456789012:a1b2c3d4e5/realtime/$connect"


def test_migrate_bootstraps_aurora_and_is_idempotent(migrations) -> None:
    assert migrations == [{"bootstrap": "done", "migrations": "head", "seed": "synthetic"}] * 2


def test_database_follows_the_aurora_security_model(stack, migrations) -> None:
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(API / "migrations"))
    with stack.superuser() as connection:
        owner = connection.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'secondchance'").fetchone()[0]
        roles = dict(connection.execute(
            "SELECT rolname, rolsuper OR rolbypassrls FROM pg_roles WHERE rolname LIKE 'secondchance%'").fetchall())
        iam = {row[0] for row in connection.execute(
            "SELECT m.rolname FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid"
            " JOIN pg_roles m ON m.oid = a.member WHERE r.rolname = 'rds_iam'").fetchall()}
        temporary = connection.execute("SELECT has_database_privilege('public', 'secondchance', 'TEMPORARY')").fetchone()[0]
        head = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert owner == "secondchance_migrator"
    assert not any(roles.values()), f"privileged roles: {roles}"
    assert {"secondchance_app", "secondchance_migrator", "secondchance_maintenance"} <= iam
    assert temporary is False
    assert head == ScriptDirectory.from_config(config).get_current_head()
    with pytest.raises(psycopg.OperationalError):  # like Aurora's rds.force_ssl: no plaintext connections
        psycopg.connect(host="127.0.0.1", port=19432, user="postgres", dbname="secondchance", sslmode="disable").close()


def test_demo_seed_loads_knowledge_through_s3_and_is_idempotent(knowledge) -> None:
    for run in knowledge:
        assert run["documents"] > 0 and set(run["outcomes"]) == {"published"}, run


def test_tool_executor_answers_through_the_lambda_runtime(stack, knowledge) -> None:
    result = stack.invoke("tool-executor", {"name": "knowledge_search", "arguments": SEARCH, "context": MCP_CONTEXT})

    assert "errorMessage" not in result, result
    assert result["hits"] and all(isinstance(hit["score"], float) for hit in result["hits"])


def test_gateway_reaches_the_executor_through_lambda_invoke(stack, knowledge) -> None:
    allowed = stack.invoke("mcp-gateway", {"name": "knowledge_search", "arguments": SEARCH, "context": MCP_CONTEXT})
    denied = stack.invoke("mcp-gateway", {"name": "knowledge_search", "arguments": SEARCH,
                                          "context": MCP_CONTEXT | {"agent": "intruder"}})

    assert allowed["result"]["hits"], allowed
    assert denied["status_code"] == 403, denied


def test_api_runs_behind_the_lambda_web_adapter(stack, knowledge) -> None:
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert stack.http("GET", "/health") == (200, {"status": "ok"})
    status, me = stack.http("GET", "/me", subject=COORDINATOR)
    assert status == 200 and me["subject"] == COORDINATOR
    assert stack.http("GET", "/me", token=stack.token(COORDINATOR, key=stranger))[0] == 401
    status, hits = stack.http("POST", "/knowledge/search", subject=COORDINATOR, tenant=TENANT_IT,
                              json_body={"query": SEARCH["query"], "language": "it"})
    assert status == 200 and hits


def test_upload_is_ingested_by_the_jobs_function(stack, knowledge) -> None:
    pdf = make_pdf([[
        "1 Sanificazione del furgone refrigerato",
        "Il furgone refrigerato va sanificato dopo ogni consegna di latticini, yogurt e formaggi freschi.",
        "Si usano detergenti alimentari, si risciacqua e si lascia asciugare con le porte aperte per dieci minuti.",
        "2 Registrazione",
        "Il volontario annota data, ora, prodotto usato e temperatura del vano nel registro di bordo.",
        "Se la temperatura supera i quattro gradi il carico successivo non parte e si avvisa il coordinatore.",
    ]])
    boundary = "emulation" + uuid.uuid4().hex
    fields = {"space_id": str(_id("space/it/internal")), "title": "Sanificazione del furgone (emulazione)",
              "language": "it", "document_type": "procedure"}
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="furgone.pdf"\r\n'
             "Content-Type: application/pdf\r\n\r\n").encode() + pdf + f"\r\n--{boundary}--\r\n".encode()

    status, job = stack.http("POST", "/documents", subject=ADMIN, tenant=TENANT_IT,
                             multipart=(f"multipart/form-data; boundary={boundary}", body))
    assert status == 202, job
    outcomes = []
    for _ in range(10):
        outcomes += stack.deliver("jobs", "jobs", matching=job["id"])
        if outcomes:
            break
    assert outcomes == [{"batchItemFailures": []}]
    assert stack.http("GET", f"/ingestion/jobs/{job['id']}", subject=ADMIN, tenant=TENANT_IT)[1]["status"] == "published"
    status, hits = stack.http("POST", "/knowledge/search", subject=COORDINATOR, tenant=TENANT_IT,
                              json_body={"query": "sanificare il furgone dei latticini", "language": "it"})
    assert any(hit["document_id"] == job["document_id"] for hit in hits)


def test_agent_run_flows_through_worker_gateway_and_executor(stack, knowledge) -> None:
    status, created = stack.http("POST", "/agent-runs", subject=COORDINATOR, tenant=TENANT_IT,
                                 json_body={"task": TASK})
    assert status == 202, created
    deadline, run = time.monotonic() + 240, None
    while time.monotonic() < deadline:
        for outcome in stack.deliver("agents", "agents"):
            assert outcome == {"batchItemFailures": []}, outcome
        run = stack.http("GET", f"/agent-runs/{created['id']}", subject=COORDINATOR, tenant=TENANT_IT)[1]
        if run["status"] not in ("queued", "running"):
            break

    assert run["status"] == "succeeded", run
    assert [step["agent"] for step in run["steps"]][:3] == ["supervisor", "intake", "supervisor"]
    donation = next(f for f in run["findings"] if f.startswith("result:donation_operations:"))
    assert int(re.search(r"with (\d+) authorised sources", donation).group(1)) > 0, donation


def test_maintenance_functions_run_with_the_maintenance_role(stack, migrations) -> None:
    requeued = stack.invoke("requeue", {})
    purged = stack.invoke("retention", {})

    assert set(requeued) == {"agent_steps", "ingestion_jobs", "matching_runs", "notification_emails",
                             "expired_offers"}, requeued
    assert purged and all(isinstance(count, int) for count in purged.values()), purged


def test_agent_step_drives_a_run_as_the_state_machine_does(stack, knowledge) -> None:
    """AWS mode: Step Functions starts with the step message and loops on agent_step's output."""
    status, created = stack.http("POST", "/agent-runs", subject=COORDINATOR, tenant=TENANT_IT, json_body={"task": TASK})
    assert status == 202, created
    state = stack.take("agents", created["id"])  # the input StartExecution receives
    for _ in range(40):
        state = stack.invoke("agent-step", state)
        assert "errorMessage" not in state, state
        if state["retry"]:  # "Wait for lease": an earlier attempt still holds the step
            time.sleep(1)
        elif not state["continue"]:
            break

    run = stack.http("GET", f"/agent-runs/{created['id']}", subject=COORDINATOR, tenant=TENANT_IT)[1]
    assert (state["outcome"], run["status"]) == ("succeeded", "succeeded"), run
    donation = next(f for f in run["findings"] if f.startswith("result:donation_operations:"))
    assert int(re.search(r"with (\d+) authorised sources", donation).group(1)) > 0, donation


def test_realtime_authorizer_admits_only_valid_cognito_tokens(stack) -> None:
    def effect(protocols: str) -> str:
        response = stack.invoke("realtime-authorizer", {
            "type": "REQUEST", "methodArn": WEBSOCKET_CONNECT, "headers": {"Sec-WebSocket-Protocol": protocols},
            "requestContext": {"routeKey": "$connect", "eventType": "CONNECT", "connectionId": "authorizer-check"},
        })
        return response["policyDocument"]["Statement"][0]["Effect"]

    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert effect(f"secondchance, {stack.token(COORDINATOR)}") == "Allow"
    for protocols in (f"secondchance, {stack.token(COORDINATOR, key=stranger)}", "secondchance", "chat, token"):
        assert effect(protocols) == "Deny", protocols


def test_realtime_subscription_receives_the_events_of_its_own_run(stack, knowledge) -> None:
    status, created = stack.http("POST", "/agent-runs", subject=COORDINATOR, tenant=TENANT_IT, json_body={"task": TASK})
    assert status == 202, created
    subscribe = {"tenant_id": str(TENANT_IT), "run_id": created["id"]}

    def route(key: str, subject: str = COORDINATOR, connection: str = "emulation-connection", **extra) -> dict:
        context = {"routeKey": key, "connectionId": connection, "authorizer": {"subject": subject}}
        return stack.invoke("realtime", {"requestContext": context, **extra})

    assert route("$connect", queryStringParameters=subscribe) == {"statusCode": 200, "headers": {"Sec-WebSocket-Protocol": "secondchance"}}
    assert route("$connect", "demo-it-volunteer", "someone-else", queryStringParameters=subscribe)["statusCode"] == 403
    assert stack.subscriptions() == {"emulation-connection"}

    stack.invoke("agent-step", stack.take("agents", created["id"]))  # one step publishes run.status
    delivered = []
    for _ in range(10):
        delivered += stack.deliver("realtime-events", "realtime-publisher", matching=created["id"])
        if delivered:
            break
    assert delivered == [{"batchItemFailures": []}]

    assert route("$disconnect") == {"statusCode": 204}
    assert stack.subscriptions() == set()


def test_matching_approval_and_notification_run_through_the_lambda_functions(stack, knowledge) -> None:
    """FL-01 on the deployed shape: API -> jobs queue -> OR-Tools in the jobs function (read-only filesystem)
    -> human approval -> mission -> notify queue -> notifier function."""
    status, run = stack.http("POST", "/matching-runs", subject=COORDINATOR, tenant=TENANT_IT,
                             json_body={"time_limit_seconds": 2})
    assert status == 202, run
    outcomes = []
    for _ in range(10):
        outcomes += stack.deliver("jobs", "jobs", matching=run["id"])
        if outcomes:
            break
    assert outcomes == [{"batchItemFailures": []}]
    status, finished = stack.http("GET", f"/matching-runs/{run['id']}", subject=COORDINATOR, tenant=TENANT_IT)
    assert finished["status"] == "succeeded" and finished["solver_status"] == "OPTIMAL", finished

    proposals = stack.http("GET", "/proposals", subject=COORDINATOR, tenant=TENANT_IT)[1]
    volunteers = stack.http("GET", "/volunteers", subject=COORDINATOR, tenant=TENANT_IT)[1]
    proposal = next(p for p in proposals if p["run_id"] == run["id"])
    status, decided = stack.http("POST", f"/proposals/{proposal['id']}/decision", subject=COORDINATOR, tenant=TENANT_IT,
                                 json_body={"approve": True, "content_sha256": proposal["content_sha256"],
                                            "volunteer_membership_id": volunteers[0]["membership_id"]})
    assert status == 200, decided

    delivered = []
    for _ in range(10):
        delivered += stack.deliver("notify", "notifier", matching="mission_assigned")
        if delivered:
            break
    assert delivered == [{"batchItemFailures": []}]
    status, mission = stack.http("GET", f"/missions/{decided['mission_id']}", subject=COORDINATOR, tenant=TENANT_IT)
    assert status == 200 and mission["status"] == "assigned", mission
