"""FR-026: the notifier resolves addresses in the identity provider and sends fixed, data-free templates."""

import pytest

from secondchance.notify import LocalDirectory, PermanentFailure, handle, render
from secondchance.queues import MalformedMessage

MESSAGE = {"type": "email", "tenant_id": "6f1b0c38-4a5e-4c55-9b0e-2c8f2b7f0a11",
           "delivery_id": "0d2b7f2c-1f4e-4c4d-9a55-7e1f6c3b2a10", "recipient": "demo-it-volunteer",
           "kind": "mission_assigned", "language": "it", "correlation_id": "c-1"}


class Recorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.error = error

    def send(self, to: str, subject: str, body: str) -> None:
        if self.error:
            raise self.error
        self.sent.append((to, subject, body))


class NoOne:
    def email_for(self, subject: str) -> None:
        return None


def test_an_assigned_mission_is_mailed_in_the_network_language() -> None:
    mailer = Recorder()
    assert handle(MESSAGE, LocalDirectory("example.test"), mailer, "https://app.example") == "sent"
    [(to, subject, body)] = mailer.sent
    assert to == "demo-it-volunteer@example.test" and subject == "Nuova missione in SecondChance"
    assert "https://app.example/missions" in body and "dati dei beneficiari" in body


@pytest.mark.parametrize("language", ["en", "da", "pl", "it", "xx"])
def test_every_template_exists_and_holds_no_data(language: str) -> None:
    for kind in ("mission_assigned", "mission_cancelled"):
        subject, body = render(kind, language, "https://app.example/")
        assert subject and "https://app.example/missions" in body
        assert "@" not in body and "kg" not in body  # no contacts, no offer details


def test_unknown_recipient_and_refused_address_are_not_retried() -> None:
    assert handle(MESSAGE, NoOne(), Recorder(), "https://app.example") == "recipient_unknown"
    refused = Recorder(PermanentFailure("MessageRejected"))
    assert handle(MESSAGE, LocalDirectory(), refused, "https://app.example") == "refused"


def test_transient_failures_raise_for_sqs_to_retry() -> None:
    with pytest.raises(ConnectionError):
        handle(MESSAGE, LocalDirectory(), Recorder(ConnectionError("smtp down")), "https://app.example")


@pytest.mark.parametrize(
    "broken",
    [MESSAGE | {"type": "sms"}, MESSAGE | {"kind": "proposals_ready"}, MESSAGE | {"recipient": 'x" or sub = "y'},
     {k: v for k, v in MESSAGE.items() if k != "recipient"}, MESSAGE | {"delivery_id": "not-a-uuid"}],
    ids=["channel", "kind-without-email", "filter-injection", "missing-recipient", "bad-id"],
)
def test_malformed_messages_are_dropped(broken: dict) -> None:
    with pytest.raises(MalformedMessage):
        handle(broken, LocalDirectory(), Recorder(), "https://app.example")
