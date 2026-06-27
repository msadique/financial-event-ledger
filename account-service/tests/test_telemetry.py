from types import SimpleNamespace

from fastapi import FastAPI
import pytest
from opentelemetry.context import attach, detach
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

import app.core.telemetry as telemetry
from app.core.config import Settings
from app.core.tracing import current_otel_trace_id


def test_trace_export_endpoint_and_disabled_configuration():
    assert telemetry.trace_export_endpoint("http://collector:4318") == "http://collector:4318/v1/traces"
    assert telemetry.trace_export_endpoint("http://collector:4318/v1/traces") == "http://collector:4318/v1/traces"
    assert telemetry.configure_telemetry(FastAPI(), Settings(otel_enabled=False)) is None


def test_configure_telemetry_enabled(monkeypatch):
    calls = {}

    class FakeProvider:
        def __init__(self, resource): calls["resource"] = resource
        def add_span_processor(self, processor): calls["processor"] = processor

    class FakeExporter:
        def __init__(self, endpoint, timeout): calls["exporter"] = (endpoint, timeout)

    class FakeProcessor:
        def __init__(self, exporter): calls["processor_exporter"] = exporter

    class FakeFastAPI:
        @staticmethod
        def instrument_app(app, **kwargs): calls["fastapi"] = kwargs

    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setattr(telemetry, "TracerProvider", FakeProvider)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", FakeProcessor)
    monkeypatch.setattr(telemetry, "FastAPIInstrumentor", FakeFastAPI)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: calls.setdefault("provider", provider))

    app = FastAPI()
    provider = telemetry.configure_telemetry(app, Settings(otel_enabled=True))
    assert provider is calls["provider"]
    assert app.state.otel_fastapi_instrumented is True


def test_shutdown_and_current_trace_id():
    calls = []
    provider = SimpleNamespace(
        force_flush=lambda timeout_millis: calls.append(("flush", timeout_millis)),
        shutdown=lambda: calls.append(("shutdown", None)),
    )
    telemetry.shutdown_telemetry(provider)
    telemetry.shutdown_telemetry(None)
    assert calls == [("flush", 5000), ("shutdown", None)]

    context = SpanContext(
        trace_id=int("a" * 32, 16),
        span_id=int("b" * 16, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=None,
    )
    token = attach(set_span_in_context(NonRecordingSpan(context)))
    try:
        assert current_otel_trace_id() == "a" * 32
    finally:
        detach(token)


def test_configure_telemetry_reuses_existing_instrumentation(monkeypatch):
    calls = {"fastapi": 0}
    provider = object()

    class FakeFastAPI:
        @staticmethod
        def instrument_app(_app, **_kwargs):
            calls["fastapi"] += 1

    monkeypatch.setattr(telemetry, "_provider", provider)
    monkeypatch.setattr(telemetry, "FastAPIInstrumentor", FakeFastAPI)

    app = FastAPI()
    app.state.otel_fastapi_instrumented = True
    settings = Settings(otel_enabled=True)

    assert telemetry.configure_telemetry(app, settings) is provider
    assert calls["fastapi"] == 0

    second_app = FastAPI()
    assert telemetry.configure_telemetry(second_app, settings) is provider
    assert calls["fastapi"] == 1


@pytest.mark.asyncio
async def test_tracing_middleware_sets_span_attribute_and_otel_header(monkeypatch):
    from fastapi import Request
    from fastapi.responses import Response

    from app.core import tracing

    attributes = {}

    class RecordingSpan:
        def is_recording(self):
            return True

        def set_attribute(self, key, value):
            attributes[key] = value

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/health",
            "raw_path": b"/health",
            "query_string": b"",
            "headers": [(b"x-trace-id", b"account-correlation")],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "root_path": "",
        }
    )

    monkeypatch.setattr(tracing.trace, "get_current_span", lambda: RecordingSpan())
    monkeypatch.setattr(tracing, "current_otel_trace_id", lambda: "e" * 32)

    async def call_next(_request):
        return Response("ok")

    response = await tracing.tracing_middleware(request, call_next)

    assert attributes["app.correlation_id"] == "account-correlation"
    assert response.headers["X-Trace-ID"] == "account-correlation"
    assert response.headers["X-OpenTelemetry-Trace-ID"] == "e" * 32


def test_transaction_schema_invalid_currency_and_naive_timestamp():
    from pydantic import ValidationError

    from app.schemas.accounts import TransactionCreate

    base = {
        "eventId": "evt-schema-otel",
        "accountId": "acct-schema-otel",
        "type": "CREDIT",
        "amount": "1.00",
        "currency": "USD",
        "eventTimestamp": "2026-06-27T10:00:00Z",
    }

    with pytest.raises(ValidationError, match="currency must contain three letters"):
        TransactionCreate(**{**base, "currency": "U1D"})

    with pytest.raises(ValidationError, match="eventTimestamp must include timezone"):
        TransactionCreate(**{**base, "eventTimestamp": "2026-06-27T10:00:00"})
