"""Logs, traces and metrics (ADR-012). Same code locally and on AWS: only the OTLP endpoint changes."""

import json
import logging
import os
import re
import uuid
from contextvars import ContextVar

from opentelemetry import metrics, trace

from secondchance.privacy import redact

CORRELATION_HEADER = b"x-correlation-id"
_VALID_CORRELATION_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
meter = metrics.get_meter("secondchance")


def current_correlation_id() -> str:
    """The request's correlation ID, or a fresh one outside a request (workers, CLI)."""
    return correlation_id.get() or str(uuid.uuid4())


class RedactingFilter(logging.Filter):
    """Runs on every handler before anything leaves the process (stdout or OTLP).

    Redacts the message, replaces exceptions with type and redacted text (stack frames
    can carry request data) and attaches the correlation ID.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = redact(record.getMessage()), None
        if record.exc_info and record.exc_info[0]:
            record.error = f"{record.exc_info[0].__name__}: {redact(str(record.exc_info[1]))}"
            record.exc_info, record.exc_text = None, None
        record.correlation_id = correlation_id.get() or None
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, joined to the active trace."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            payload["trace_id"] = format(span.trace_id, "032x")
            payload["span_id"] = format(span.span_id, "016x")
        if getattr(record, "error", None):
            payload["error"] = record.error
        return json.dumps(payload, ensure_ascii=False)


def _add_handler(handler: logging.Handler) -> None:
    handler.addFilter(RedactingFilter())
    logging.getLogger().addHandler(handler)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = []
    _add_handler(handler)
    root.setLevel(os.environ.get("SECONDCHANCE_LOG_LEVEL", "INFO"))


class CorrelationIdMiddleware:
    """Accepts a well-formed X-Correlation-ID or mints one, and echoes it on the response."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(CORRELATION_HEADER, b"").decode("latin-1")
        value = incoming if _VALID_CORRELATION_ID.fullmatch(incoming) else str(uuid.uuid4())
        token = correlation_id.set(value)

        async def send_with_header(message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (CORRELATION_HEADER, value.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id.reset(token)


def configure_telemetry(app=None, engine=None) -> bool:
    """Exports via OTLP when OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise stays off.

    Locally the endpoint is the otel-lgtm container, on AWS the ADOT collector.
    OTEL_SERVICE_NAME and the other standard OTEL_* variables are honoured.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False

    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "secondchance-api")})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())])
    )
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    _add_handler(LoggingHandler(logger_provider=logger_provider))  # same redaction as stdout
    if app is not None:
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine)
    return True
