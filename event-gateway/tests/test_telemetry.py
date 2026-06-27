from types import SimpleNamespace

from fastapi import FastAPI
import pytest
from opentelemetry.context import attach, detach
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

import app.core.telemetry as telemetry
from app.core.config import Settings
from app.core.tracing import current_otel_trace_id


def test_trace_export_endpoint():
    assert telemetry.trace_export_endpoint("http://collector:4318") == "http://collector:4318/v1/traces"
    assert telemetry.trace_export_endpoint("http://collector:4318/v1/traces") == "http://collector:4318/v1/traces"


def test_configure_telemetry_disabled():
    assert telemetry.configure_telemetry(FastAPI(), Settings(otel_enabled=False), instrument_httpx=True) is None


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

    class FakeHttpxInstance:
        def instrument(self, **kwargs): calls["httpx"] = kwargs

    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setattr(telemetry, "_httpx_instrumented", False)
    monkeypatch.setattr(telemetry, "TracerProvider", FakeProvider)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", FakeProcessor)
    monkeypatch.setattr(telemetry, "FastAPIInstrumentor", FakeFastAPI)
    monkeypatch.setattr(telemetry, "HTTPXClientInstrumentor", lambda: FakeHttpxInstance())
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: calls.setdefault("provider", provider))

    app = FastAPI()
    settings = Settings(otel_enabled=True, otel_exporter_otlp_endpoint="http://collector:4318")
    provider = telemetry.configure_telemetry(app, settings, instrument_httpx=True)
    assert provider is calls["provider"]
    assert calls["exporter"][0].endswith("/v1/traces")
    assert app.state.otel_fastapi_instrumented is True
    assert "httpx" in calls


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
        trace_id=int("1" * 32, 16),
        span_id=int("2" * 16, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=None,
    )
    token = attach(set_span_in_context(NonRecordingSpan(context)))
    try:
        assert current_otel_trace_id() == "1" * 32
    finally:
        detach(token)


def test_configure_telemetry_reuses_existing_instrumentation(monkeypatch):
    calls = {"fastapi": 0, "httpx": 0}
    provider = object()

    class FakeFastAPI:
        @staticmethod
        def instrument_app(_app, **_kwargs):
            calls["fastapi"] += 1

    class FakeHttpx:
        def instrument(self, **_kwargs):
            calls["httpx"] += 1

    monkeypatch.setattr(telemetry, "_provider", provider)
    monkeypatch.setattr(telemetry, "_httpx_instrumented", True)
    monkeypatch.setattr(telemetry, "FastAPIInstrumentor", FakeFastAPI)
    monkeypatch.setattr(telemetry, "HTTPXClientInstrumentor", lambda: FakeHttpx())

    app = FastAPI()
    app.state.otel_fastapi_instrumented = True
    settings = Settings(otel_enabled=True)

    assert telemetry.configure_telemetry(app, settings, instrument_httpx=True) is provider
    assert calls == {"fastapi": 0, "httpx": 0}

    second_app = FastAPI()
    assert telemetry.configure_telemetry(second_app, settings, instrument_httpx=False) is provider
    assert calls == {"fastapi": 1, "httpx": 0}


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
            "path": "/events",
            "raw_path": b"/events",
            "query_string": b"",
            "headers": [(b"x-trace-id", b"correlation-123")],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "root_path": "",
        }
    )

    monkeypatch.setattr(tracing.trace, "get_current_span", lambda: RecordingSpan())
    monkeypatch.setattr(tracing, "current_otel_trace_id", lambda: "f" * 32)

    async def call_next(_request):
        return Response("ok")

    response = await tracing.tracing_middleware(request, call_next)

    assert attributes["app.correlation_id"] == "correlation-123"
    assert response.headers["X-Trace-ID"] == "correlation-123"
    assert response.headers["X-OpenTelemetry-Trace-ID"] == "f" * 32
