from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None
_httpx_instrumented = False


def trace_export_endpoint(base_endpoint: str) -> str:
    endpoint = base_endpoint.rstrip("/")
    if endpoint.endswith("/v1/traces"):
        return endpoint
    return f"{endpoint}/v1/traces"


def configure_telemetry(app: Any, settings: Any, *, instrument_httpx: bool = False):
    """Configure FastAPI tracing and OTLP/HTTP export when enabled."""
    if not settings.otel_enabled:
        return None

    global _provider, _httpx_instrumented
    if _provider is None:
        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.otel_service_version,
                "deployment.environment.name": settings.otel_environment,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=trace_export_endpoint(settings.otel_exporter_otlp_endpoint),
            timeout=settings.otel_export_timeout_seconds,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _provider = provider

    if not getattr(app.state, "otel_fastapi_instrumented", False):
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=_provider,
            excluded_urls=settings.otel_excluded_urls,
        )
        app.state.otel_fastapi_instrumented = True

    if instrument_httpx and not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(tracer_provider=_provider)
        _httpx_instrumented = True

    return _provider


def shutdown_telemetry(provider) -> None:
    if provider is None:
        return
    provider.force_flush(timeout_millis=5_000)
    provider.shutdown()
