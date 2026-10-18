"""Authenticated WebSocket subscriptions and server-pushed agent-run events."""

import json
import logging
import os
import time
import uuid

from secondchance.auth import verify
from secondchance.db import tenant_transaction
from secondchance.identity import memberships

log = logging.getLogger(__name__)


def _policy(principal: str, effect: str, resource: str, context: dict | None = None) -> dict:
    return {
        "principalId": principal,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}],
        },
        "context": context or {},
    }


def _subprotocol_token(event: dict) -> str | None:
    headers = {str(key).lower(): value for key, value in (event.get("headers") or {}).items()}
    protocols = [part.strip() for part in str(headers.get("sec-websocket-protocol", "")).split(",")]
    if len(protocols) != 2 or protocols[0] != "secondchance":
        return None
    return protocols[1] or None


def websocket_authorizer(event: dict, context) -> dict:
    """Authorize only ``$connect``; JWT claims never become application roles."""
    resource = event.get("methodArn", "*")
    token = _subprotocol_token(event)
    if token is None:
        return _policy("anonymous", "Deny", resource)
    try:
        payload = verify(token)
        subject = payload["sub"]
        if not isinstance(subject, str) or not 0 < len(subject) <= 255:
            raise ValueError("invalid subject")
    except Exception:  # noqa: BLE001 - an authorizer must convert every token failure to Deny
        return _policy("anonymous", "Deny", resource)
    return _policy(subject, "Allow", resource, {"subject": subject})


def _table():
    import boto3

    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-central-1")).Table(
        os.environ["SECONDCHANCE_REALTIME_TABLE"]
    )


def websocket_handler(event: dict, context) -> dict:
    """Register a run subscription on connect and remove it on disconnect."""
    request = event.get("requestContext") or {}
    route = request.get("routeKey")
    connection_id = request.get("connectionId")
    table = _table()
    if route == "$disconnect":
        if connection_id:
            table.delete_item(Key={"connection_id": connection_id})
        return {"statusCode": 204}
    if route != "$connect" or not connection_id:
        return {"statusCode": 400, "body": "unsupported WebSocket route"}

    subject = (request.get("authorizer") or {}).get("subject")
    query = event.get("queryStringParameters") or {}
    try:
        tenant_id, run_id = uuid.UUID(query["tenant_id"]), uuid.UUID(query["run_id"])
    except (KeyError, TypeError, ValueError):
        return {"statusCode": 400, "body": "tenant_id and run_id are required"}

    membership = next(
        (item for item in memberships(subject) if item.tenant_id == tenant_id and item.status == "active"), None
    )
    if membership is None:
        return {"statusCode": 403, "body": "active membership required"}
    with tenant_transaction(tenant_id, membership.role, subject) as session:
        from sqlalchemy import text

        owner = session.execute(
            text("SELECT requested_by FROM agent_run WHERE id = :run"), {"run": run_id}
        ).scalar_one_or_none()
    if owner != subject:
        return {"statusCode": 403, "body": "run subscription denied"}

    table.put_item(Item={
        "connection_id": connection_id,
        "run_id": str(run_id),
        "subject": subject,
        "tenant_id": str(tenant_id),
        "expires_at": int(time.time()) + 7200,
    })
    return {"statusCode": 200, "headers": {"Sec-WebSocket-Protocol": "secondchance"}}


class RealtimePublisher:
    def __init__(self, table, management_client) -> None:
        self.table = table
        self.management = management_client

    @classmethod
    def from_environment(cls) -> "RealtimePublisher":
        import boto3

        endpoint = os.environ["SECONDCHANCE_REALTIME_MANAGEMENT_ENDPOINT"]
        return cls(_table(), boto3.client("apigatewaymanagementapi", endpoint_url=endpoint))

    def publish(self, run_id: str, event: dict) -> None:
        payload = json.dumps(event, separators=(",", ":")).encode()
        cursor = None
        while True:
            query = {
                "IndexName": "run_id-index",
                "KeyConditionExpression": "run_id = :run",
                "ExpressionAttributeValues": {":run": run_id},
            }
            if cursor is not None:
                query["ExclusiveStartKey"] = cursor
            response = self.table.query(**query)
            for item in response.get("Items", []):
                connection_id = item["connection_id"]
                try:
                    self.management.post_to_connection(ConnectionId=connection_id, Data=payload)
                except Exception as exc:  # noqa: BLE001 - stale WebSocket cleanup boundary
                    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                    if code != "GoneException":
                        raise
                    self.table.delete_item(Key={"connection_id": connection_id})
            cursor = response.get("LastEvaluatedKey")
            if cursor is None:
                return


def publish_run_event(run_id: str, event: dict) -> None:
    try:
        queue_url = os.environ.get("SECONDCHANCE_REALTIME_QUEUE_URL")
        if queue_url:
            import boto3

            boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "eu-central-1")).send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({"run_id": run_id, "event": event}, separators=(",", ":")),
            )
            return
        if not os.environ.get("SECONDCHANCE_REALTIME_TABLE"):
            return
        RealtimePublisher.from_environment().publish(run_id, event)
    except Exception:
        log.exception("realtime run event delivery failed", extra={"run_id": run_id})
