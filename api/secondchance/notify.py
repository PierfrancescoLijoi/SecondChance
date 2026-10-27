"""Notification delivery worker (FR-026): `python -m secondchance.notify`; on AWS the `notifier` Lambda.

It has no database access by design. A message from the `notify` queue carries a delivery id, the
recipient's identity-provider subject, a notification kind and a language. The address comes from
the identity provider (Cognito on AWS, Microsoft Graph on Azure: domain tables never store contacts, ADR-014); the text comes
from a fixed template that says only that something is waiting in SecondChance. No offer details,
no names and no beneficiary data ever leave in an email.

Failures that retrying cannot fix (unknown recipient, an address SES refuses) are dropped and
counted; everything else raises, so SQS retries it and moves it to the DLQ after five attempts.
On AWS the function runs outside the VPC, like the real-time relay: Cognito user pools with a
hosted domain are not reachable through PrivateLink, and the function holds no data permission.
"""

import logging
import os
import re
import smtplib
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from secondchance.observability import configure_logging, configure_telemetry, meter
from secondchance.queues import MalformedMessage, Queue, drain, open_queue, require

log = logging.getLogger(__name__)
SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,254}$")  # nothing that could escape a Cognito filter
OBJECT_ID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")  # an Entra object id, the only thing put in a Graph URL
LANGUAGES = ("en", "da", "pl", "it")
PERMANENT_SES_ERRORS = frozenset({"MessageRejected", "MailFromDomainNotVerifiedException", "BadRequestException"})

emails = meter.create_counter("secondchance.notifications.email", description="Notification emails by outcome")

TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "mission_assigned": {
        "en": ("New mission in SecondChance", "A pickup and delivery mission has been assigned to you.\n"
               "Open SecondChance to see the details, then accept or decline it:\n{url}/missions"),
        "da": ("Ny opgave i SecondChance", "Du har fået tildelt en afhentnings- og leveringsopgave.\n"
               "Åbn SecondChance for at se detaljerne og acceptere eller afvise den:\n{url}/missions"),
        "pl": ("Nowa misja w SecondChance", "Przydzielono Ci misję odbioru i dostawy.\n"
               "Otwórz SecondChance, aby zobaczyć szczegóły i ją przyjąć lub odrzucić:\n{url}/missions"),
        "it": ("Nuova missione in SecondChance", "Ti è stata assegnata una missione di ritiro e consegna.\n"
               "Apri SecondChance per vedere i dettagli e accettarla o rifiutarla:\n{url}/missions"),
    },
    "mission_cancelled": {
        "en": ("Mission cancelled in SecondChance", "A mission assigned to you has been cancelled by a coordinator.\n"
               "Open SecondChance for your current missions:\n{url}/missions"),
        "da": ("Opgave annulleret i SecondChance", "En opgave, du var tildelt, er blevet annulleret af en koordinator.\n"
               "Åbn SecondChance for at se dine aktuelle opgaver:\n{url}/missions"),
        "pl": ("Misja anulowana w SecondChance", "Misja przydzielona Tobie została anulowana przez koordynatora.\n"
               "Otwórz SecondChance, aby zobaczyć swoje bieżące misje:\n{url}/missions"),
        "it": ("Missione annullata in SecondChance", "Una missione assegnata a te è stata annullata da un coordinatore.\n"
               "Apri SecondChance per le tue missioni attuali:\n{url}/missions"),
    },
}
FOOTER = {
    "en": "This message contains no personal or beneficiary data. Do not reply.",
    "da": "Denne besked indeholder ingen personoplysninger eller data om modtagere. Svar ikke.",
    "pl": "Ta wiadomość nie zawiera danych osobowych ani danych beneficjentów. Nie odpowiadaj.",
    "it": "Questo messaggio non contiene dati personali né dati dei beneficiari. Non rispondere.",
}


def render(kind: str, language: str, web_url: str) -> tuple[str, str]:
    lang = language if language in LANGUAGES else "en"
    subject, body = TEMPLATES[kind][lang]
    return subject, f"{body.format(url=web_url.rstrip('/'))}\n\n{FOOTER[lang]}\n"


class Directory(Protocol):
    def email_for(self, subject: str) -> str | None: ...


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class PermanentFailure(Exception):
    """Retrying cannot deliver this message (unknown recipient, refused address)."""


class LocalDirectory:
    """Synthetic users have no mailbox: every subject maps to the local mail catcher's domain."""

    def __init__(self, domain: str = "volunteers.secondchance.local") -> None:
        self.domain = domain

    def email_for(self, subject: str) -> str | None:
        return f"{subject}@{self.domain}"


class CognitoDirectory:
    """The verified email of a Cognito user, looked up by `sub` (the only identifier SecondChance keeps)."""

    def __init__(self, user_pool_id: str, client=None) -> None:
        if client is None:
            import boto3

            client = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
        self.client, self.user_pool_id = client, user_pool_id

    def email_for(self, subject: str) -> str | None:
        users = self.client.list_users(
            UserPoolId=self.user_pool_id, Filter=f'sub = "{subject}"', Limit=1,
            AttributesToGet=["email", "email_verified"],
        ).get("Users", [])
        if not users or not users[0].get("Enabled", True):
            return None
        attributes = {a["Name"]: a.get("Value") for a in users[0].get("Attributes", [])}
        return attributes.get("email") if attributes.get("email_verified") == "true" else None


class SesMailer:
    def __init__(self, sender: str, client=None) -> None:
        if client is None:
            import boto3

            client = boto3.client("sesv2", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
        self.client, self.sender = client, sender

    def send(self, to: str, subject: str, body: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.send_email(
                FromEmailAddress=self.sender,
                Destination={"ToAddresses": [to]},
                Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}}},
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in PERMANENT_SES_ERRORS:  # e.g. SES sandbox and an unverified recipient
                raise PermanentFailure(code) from error
            raise


class GraphDirectory:
    """The mailbox of an Entra user, looked up by object id (the subject Azure sign-in puts in the API)."""

    SCOPE = "https://graph.microsoft.com/.default"

    def __init__(self, http=None, token=None) -> None:
        import httpx

        self.http = http or httpx.Client(base_url="https://graph.microsoft.com/v1.0", timeout=10)
        self.token = token or self._token

    @staticmethod
    def _token() -> str:
        from secondchance.cloud import bearer

        return bearer(GraphDirectory.SCOPE)

    def email_for(self, subject: str) -> str | None:
        if not OBJECT_ID.fullmatch(subject):
            return None  # not an Entra user (a synthetic demo subject): nothing to look up
        response = self.http.get(
            f"/users/{subject}", params={"$select": "accountEnabled,mail,otherMails"},
            headers={"Authorization": f"Bearer {self.token()}"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        user = response.json()
        if not user.get("accountEnabled", True):
            return None
        return user.get("mail") or next(iter(user.get("otherMails") or []), None)


class AcsMailer:
    """Azure Communication Services Email, authenticated with the notifier's managed identity."""

    def __init__(self, sender: str, endpoint: str | None = None, client=None) -> None:
        if client is None:
            from azure.communication.email import EmailClient

            from secondchance.cloud import azure_credential

            client = EmailClient(endpoint or os.environ["SECONDCHANCE_ACS_ENDPOINT"], azure_credential())
        self.client, self.sender = client, sender

    def send(self, to: str, subject: str, body: str) -> None:
        from azure.core.exceptions import HttpResponseError

        message = {
            "senderAddress": self.sender,
            "recipients": {"to": [{"address": to}]},
            "content": {"subject": subject, "plainText": body},
        }
        try:
            result = self.client.begin_send(message).result()
        except HttpResponseError as error:
            if error.status_code in (400, 422):  # a recipient or sender ACS refuses: retrying cannot fix it
                raise PermanentFailure(str(error.error.code if error.error else error.status_code)) from error
            raise
        if result.get("status") != "Succeeded":
            raise RuntimeError(f"ACS did not deliver the message: {result.get('status')}")


class SmtpMailer:
    """Local mail catcher (Mailpit in docker-compose.yml): the same messages, never leaving the machine."""

    def __init__(self, host: str, port: int, sender: str) -> None:
        self.host, self.port, self.sender = host, port, sender

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self.sender, to, subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.send_message(message)


class LogMailer:
    """No mail transport configured: record that a message would have left, without the address."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.info("email not sent (no mailer configured): %s", subject)


def handle(body: object, directory: Directory, mailer: Mailer, web_url: str) -> str:
    message = require(body, "type", "tenant_id", "delivery_id", "recipient", "kind")
    if message["type"] != "email":
        raise MalformedMessage(f"unknown notification type {message['type']!r}")
    if message["kind"] not in TEMPLATES:
        raise MalformedMessage(f"no email template for {message['kind']!r}")
    if not isinstance(message["recipient"], str) or not SUBJECT.fullmatch(message["recipient"]):
        raise MalformedMessage("recipient is not a valid subject")
    address = directory.email_for(message["recipient"])
    if address is None:
        emails.add(1, {"outcome": "recipient_unknown"})
        return "recipient_unknown"  # e.g. a synthetic demo user, or an account without a verified email
    subject, text = render(message["kind"], str(message.get("language", "en")), web_url)
    try:
        mailer.send(address, subject, text)
    except PermanentFailure as failure:
        log.warning("email refused permanently: %s", failure)
        emails.add(1, {"outcome": "refused"})
        return "refused"
    emails.add(1, {"outcome": "sent"})
    return "sent"


@lru_cache
def configured() -> tuple[Directory, Mailer, str]:
    """Adapters from the environment (NFR-013): Cognito + SES on AWS, Graph + ACS on Azure, the local catcher in Compose."""
    kind = os.environ.get("SECONDCHANCE_NOTIFY_DIRECTORY", "local")
    if kind == "cognito":
        directory: Directory = CognitoDirectory(os.environ["SECONDCHANCE_COGNITO_USER_POOL_ID"])
    elif kind == "graph":
        directory = GraphDirectory()
    else:
        directory = LocalDirectory(os.environ.get("SECONDCHANCE_LOCAL_MAIL_DOMAIN", "volunteers.secondchance.local"))
    sender = os.environ.get("SECONDCHANCE_MAIL_FROM", "SecondChance <no-reply@secondchance.local>")
    mode = os.environ.get("SECONDCHANCE_MAILER", "log")
    if mode == "ses":
        mailer: Mailer = SesMailer(sender)
    elif mode == "acs":
        mailer = AcsMailer(sender)
    elif mode == "smtp":
        mailer = SmtpMailer(os.environ.get("SECONDCHANCE_SMTP_HOST", "mail"),
                            int(os.environ.get("SECONDCHANCE_SMTP_PORT", "1025")), sender)
    else:
        mailer = LogMailer()
    return directory, mailer, os.environ.get("SECONDCHANCE_WEB_URL", "http://localhost:8088")


def process(body: object) -> str:
    directory, mailer, web_url = configured()
    return handle(body, directory, mailer, web_url)


def drain_queue(queue: Queue, wait_seconds: int = 0, max_batches: int | None = None) -> int:
    return drain(queue, process, wait_seconds, max_batches)


if __name__ == "__main__":
    configure_logging()
    configure_telemetry()
    drain_queue(open_queue("SECONDCHANCE_QUEUE_NOTIFY", "notify"), wait_seconds=10)
