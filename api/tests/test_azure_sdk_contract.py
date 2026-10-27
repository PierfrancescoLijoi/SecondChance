"""The parts of the Azure and OpenAI SDKs the adapters call, checked against the installed packages (ADR-023).

The adapter tests use fakes, so a renamed keyword in a new SDK release would pass them and fail in production.
These tests read the real signatures and the REST field names: when `uv lock` brings a release that moves one of
them, the build fails here instead of in a container nobody is watching.
"""

import inspect

import openai
import pytest
from azure.communication.email import EmailClient
from azure.messaging.webpubsubservice import WebPubSubServiceClient
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from azure.servicebus import AutoLockRenewer, ServiceBusClient, ServiceBusMessage, ServiceBusReceiver, ServiceBusSender
from azure.storage.blob import BlobClient, ContainerClient


def params(function) -> set[str]:
    return set(inspect.signature(function).parameters)


def test_service_bus_calls_the_queue_adapter_makes() -> None:
    assert {"queue_name", "auto_lock_renewer", "max_wait_time"} <= params(ServiceBusClient.get_queue_receiver)
    assert {"max_message_count", "max_wait_time"} <= params(ServiceBusReceiver.receive_messages)
    assert {"reason", "error_description"} <= params(ServiceBusReceiver.dead_letter_message)
    assert {"message"} <= params(ServiceBusReceiver.complete_message) & params(ServiceBusReceiver.abandon_message)
    assert {"content_type", "application_properties", "correlation_id"} <= params(ServiceBusMessage.__init__)
    assert "max_lock_renewal_duration" in params(AutoLockRenewer.__init__)
    assert params(ServiceBusSender.send_messages) >= {"message"}
    assert callable(ServiceBusClient.get_queue_sender)


def test_blob_calls_the_object_store_makes() -> None:
    assert {"name", "data", "overwrite"} <= params(ContainerClient.upload_blob) | {"overwrite"}  # overwrite travels in **kwargs
    assert "content_settings" in inspect.getsource(ContainerClient.upload_blob)
    assert callable(ContainerClient.download_blob) and callable(ContainerClient.get_blob_client)
    assert callable(BlobClient.get_blob_tags)


def test_web_pubsub_calls_the_realtime_adapter_makes() -> None:
    assert {"group", "message", "content_type"} <= params(WebPubSubServiceClient.send_to_group)
    documented = WebPubSubServiceClient.get_client_access_token.__doc__ or ""
    for keyword in ("user_id", "roles", "groups", "minutes_to_expire"):
        assert f":keyword {keyword}:" in documented, f"get_client_access_token no longer documents {keyword}"


def test_email_and_telemetry_calls() -> None:
    assert callable(EmailClient.begin_send)
    assert "operation_id" in params(EmailClient.begin_send)  # the message itself is the first positional parameter
    assert "kwargs" in params(AzureMonitorTraceExporter.__init__)  # connection_string and credential travel in **kwargs


@pytest.mark.parametrize("name", ["BadRequestError", "OpenAIError", "APIConnectionError", "OpenAI"])
def test_openai_names_the_model_adapter_uses(name: str) -> None:
    assert hasattr(openai, name)


def test_openai_calls_the_model_and_embedding_adapters_make() -> None:
    client = openai.OpenAI(base_url="https://example.openai.azure.com/openai/v1/", api_key=lambda: "token")
    assert {"model", "messages", "max_completion_tokens", "temperature"} <= params(client.chat.completions.create)
    assert {"model", "input", "dimensions"} <= params(client.embeddings.create)
    assert client.base_url.path.endswith("/openai/v1/")
