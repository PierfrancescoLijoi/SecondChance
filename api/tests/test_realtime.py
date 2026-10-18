"""WebSocket authentication and delivery stay independent from model output."""

import json
from unittest.mock import patch

from secondchance.realtime import RealtimePublisher, publish_run_event, websocket_authorizer


def test_websocket_authorizer_accepts_access_token_from_subprotocol() -> None:
    event = {
        "methodArn": "arn:aws:execute-api:eu-central-1:123456789012:api/prod/$connect",
        "headers": {"Sec-WebSocket-Protocol": "secondchance, signed.jwt.token"},
    }
    with patch("secondchance.realtime.verify", return_value={"sub": "coord-it"}):
        response = websocket_authorizer(event, None)

    assert response["principalId"] == "coord-it"
    assert response["context"] == {"subject": "coord-it"}
    assert response["policyDocument"]["Statement"][0]["Effect"] == "Allow"


def test_websocket_authorizer_denies_missing_or_invalid_tokens() -> None:
    event = {"methodArn": "arn:aws:execute-api:eu-central-1:123456789012:api/prod/$connect", "headers": {}}
    response = websocket_authorizer(event, None)
    assert response["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_realtime_publisher_sends_event_to_every_subscriber_and_removes_gone_connections() -> None:
    class Table:
        def query(self, **_):
            return {"Items": [{"connection_id": "open"}, {"connection_id": "gone"}]}

        def delete_item(self, **kwargs):
            assert kwargs == {"Key": {"connection_id": "gone"}}

    class Gone(Exception):
        response = {"Error": {"Code": "GoneException"}}

    class Management:
        def __init__(self):
            self.sent = []

        def post_to_connection(self, **kwargs):
            if kwargs["ConnectionId"] == "gone":
                raise Gone()
            self.sent.append(kwargs)

    management = Management()
    publisher = RealtimePublisher(Table(), management)
    publisher.publish("run-1", {"type": "run.status", "status": "running"})

    assert management.sent == [{
        "ConnectionId": "open",
        "Data": json.dumps({"type": "run.status", "status": "running"}, separators=(",", ":")).encode(),
    }]


def test_private_runtime_puts_realtime_events_on_the_relay_queue(monkeypatch) -> None:
    class Sqs:
        def __init__(self):
            self.messages = []

        def send_message(self, **message):
            self.messages.append(message)

    sqs = Sqs()
    monkeypatch.setenv("SECONDCHANCE_REALTIME_QUEUE_URL", "https://sqs.example/realtime-events")
    with patch("boto3.client", return_value=sqs):
        publish_run_event("run-1", {"type": "run.status", "outcome": "succeeded"})

    assert sqs.messages == [{
        "QueueUrl": "https://sqs.example/realtime-events",
        "MessageBody": '{"run_id":"run-1","event":{"type":"run.status","outcome":"succeeded"}}',
    }]
