"""One emulated AWS environment per test session (infra/emulation/compose.yaml).

Every function is the Lambda image deploy.sh builds, run by the AWS Runtime Interface Emulator;
these helpers talk to it the way AWS does: Invoke payloads, SQS event records, API Gateway HTTP
API v2 events and RS256 access tokens shaped like Cognito's. Start it with scripts/emulate-aws.sh.
"""

import base64
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import boto3
import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra" / "emulation" / "compose.yaml")]
IMAGES = [f"secondchance-lambda-emulator:{target}" for target in ("api", "worker", "gateway")]
PORTS = {"migrate": 19101, "demo-seed": 19102, "tool-executor": 19103, "mcp-gateway": 19104, "agents": 19105,
         "jobs": 19106, "requeue": 19107, "retention": 19108, "api": 19109, "agent-step": 19110,
         "realtime-authorizer": 19111, "realtime": 19112, "realtime-publisher": 19113}
ISSUER = "https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_EMULATION"
CLIENT_ID = "emulation-web-client"
BUCKET = "secondchance-emulation-objects"
MASTER_SECRET = "rds!cluster-emulation"
REALTIME_TABLE = "secondchance-emulation-realtime-connections"
AWS = {"region_name": "eu-central-1", "aws_access_key_id": "emulation", "aws_secret_access_key": "emulation"}


def _retry(action, attempts: int = 30):
    for attempt in range(attempts):
        try:
            return action()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(1)


class Stack:
    def __init__(self, signing_key: rsa.RSAPrivateKey) -> None:
        self.signing_key = signing_key
        self.sqs = boto3.client("sqs", endpoint_url="http://127.0.0.1:19324", **AWS)
        self.s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:18333", **AWS)
        self.secrets = boto3.client("secretsmanager", endpoint_url="http://127.0.0.1:19500", **AWS)
        self.dynamodb = boto3.client("dynamodb", endpoint_url="http://127.0.0.1:19500", **AWS)

    def prepare(self) -> None:
        """What Terraform and RDS create before the first deployment: bucket, master secret, realtime table and queue."""
        _retry(lambda: self.s3.create_bucket(Bucket=BUCKET))
        _retry(lambda: self.secrets.create_secret(
            Name=MASTER_SECRET, SecretString=json.dumps({"username": "secondchance_master", "password": "unused-under-trust"})
        ))
        _retry(lambda: self.dynamodb.create_table(  # as realtime.tf declares it
            TableName=REALTIME_TABLE, BillingMode="PAY_PER_REQUEST", KeySchema=[{"AttributeName": "connection_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "connection_id", "AttributeType": "S"}, {"AttributeName": "run_id", "AttributeType": "S"}],
            GlobalSecondaryIndexes=[{"IndexName": "run_id-index", "KeySchema": [{"AttributeName": "run_id", "KeyType": "HASH"}],
                                     "Projection": {"ProjectionType": "KEYS_ONLY"}}],
        ))
        _retry(lambda: self.sqs.create_queue(QueueName="realtime-events"))

    def invoke(self, function: str, payload: dict, timeout: float = 600) -> dict:
        url = f"http://127.0.0.1:{PORTS[function]}/2015-03-31/functions/function/invocations"
        return httpx.post(url, json=payload, timeout=timeout).json()

    def token(self, subject: str, *, key: rsa.RSAPrivateKey | None = None) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "sub": subject, "token_use": "access", "client_id": CLIENT_ID, "scope": "openid email",
                  "auth_time": now, "iat": now, "exp": now + 600, "jti": str(uuid.uuid4()), "username": subject}
        return jwt.encode(claims, key or self.signing_key, algorithm="RS256", headers={"kid": "emulation"})

    def http(self, method: str, path: str, *, subject: str | None = None, token: str | None = None,
             tenant: uuid.UUID | None = None, json_body: object = None, multipart: tuple[str, bytes] | None = None):
        """One request as API Gateway HTTP API (payload 2.0) hands it to the API function."""
        headers = {"host": "a1b2c3d4e5.execute-api.eu-central-1.amazonaws.com", "user-agent": "Amazon CloudFront",
                   "x-forwarded-proto": "https"}
        if subject or token:
            headers["authorization"] = f"Bearer {token or self.token(subject)}"
        if tenant:
            headers["x-tenant-id"] = str(tenant)
        body, binary = None, False
        if json_body is not None:
            headers["content-type"], body = "application/json", json.dumps(json_body)
        if multipart is not None:
            headers["content-type"], raw = multipart
            body, binary = base64.b64encode(raw).decode(), True
        event = {
            "version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "", "headers": headers,
            "isBase64Encoded": binary,
            "requestContext": {
                "accountId": "123456789012", "apiId": "a1b2c3d4e5", "domainName": headers["host"], "domainPrefix": "a1b2c3d4e5",
                "http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.7", "userAgent": "Amazon CloudFront"},
                "requestId": str(uuid.uuid4()), "routeKey": "$default", "stage": "$default",
                "time": time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime()), "timeEpoch": int(time.time() * 1000),
            },
        }
        if body is not None:
            event["body"] = body
        response = self.invoke("api", event, timeout=120)
        assert "statusCode" in response, f"the API function failed: {response}"
        text = base64.b64decode(response["body"]).decode() if response.get("isBase64Encoded") else response.get("body", "")
        try:
            return response["statusCode"], json.loads(text)
        except json.JSONDecodeError:
            return response["statusCode"], text

    def deliver(self, queue: str, function: str, *, matching: str | None = None) -> list[dict]:
        """One SQS event source mapping poll: receive, invoke with the records, delete what succeeded."""
        url = self.sqs.get_queue_url(QueueName=queue)["QueueUrl"]
        messages = self.sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=5, WaitTimeSeconds=1).get("Messages", [])
        messages = [m for m in messages if matching is None or matching in m["Body"]]
        if not messages:
            return []
        records = [{"messageId": m["MessageId"], "receiptHandle": m["ReceiptHandle"], "body": m["Body"], "attributes": {},
                    "messageAttributes": {}, "md5OfBody": m["MD5OfBody"], "eventSource": "aws:sqs", "awsRegion": "eu-central-1",
                    "eventSourceARN": f"arn:aws:sqs:eu-central-1:123456789012:{queue}"} for m in messages]
        outcome = self.invoke(function, {"Records": records})
        failed = {item["itemIdentifier"] for item in outcome.get("batchItemFailures", [])}
        for message in messages:
            if message["MessageId"] not in failed:
                self.sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
        return [outcome]

    def subscriptions(self) -> set[str]:
        return {item["connection_id"]["S"] for item in self.dynamodb.scan(TableName=REALTIME_TABLE)["Items"]}

    def take(self, queue: str, matching: str, rounds: int = 10) -> dict:
        """Remove one message from a queue and return its body (what Step Functions would receive as input)."""
        url = self.sqs.get_queue_url(QueueName=queue)["QueueUrl"]
        for _ in range(rounds):
            for message in self.sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages", []):
                if matching in message["Body"]:
                    self.sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
                    return json.loads(message["Body"])
        raise AssertionError(f"no message for {matching} in {queue}")

    @staticmethod
    def superuser() -> psycopg.Connection:
        return psycopg.connect(host="127.0.0.1", port=19432, user="postgres", dbname="secondchance", sslmode="require", autocommit=True)


def _compose(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*COMPOSE, *args], capture_output=True, text=True, env=env)


@pytest.fixture(scope="session")
def stack():
    missing = [image for image in IMAGES if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode]
    if missing:
        pytest.exit(f"emulator images missing ({', '.join(missing)}): run scripts/emulate-aws.sh", returncode=2)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True) | {"kid": "emulation", "alg": "RS256", "use": "sig"}
    env = os.environ | {"SECONDCHANCE_EMULATION_JWKS": json.dumps({"keys": [jwk]})}
    _compose("down", "-v", "--remove-orphans", env=env)
    started = _compose("up", "-d", "--wait", env=env)
    if started.returncode:
        pytest.fail(f"the emulated environment did not start:\n{started.stderr}")
    emulated = Stack(key)
    emulated.prepare()
    yield emulated
    if os.environ.get("SECONDCHANCE_EMULATION_KEEP") != "1":
        _compose("down", "-v", "--remove-orphans", env=env)


@pytest.fixture(scope="session")
def migrations(stack: Stack) -> list[dict]:
    """deploy.sh runs the bootstrap on every deployment: twice in a row must be harmless."""
    return [stack.invoke("migrate", {"bootstrap": True}) for _ in range(2)]


@pytest.fixture(scope="session")
def knowledge(stack: Stack, migrations: list[dict]) -> list[dict]:
    return [stack.invoke("demo-seed", {}) for _ in range(2)]
