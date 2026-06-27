from contextlib import contextmanager
from contextvars import ContextVar
import re
import uuid

from fastapi import Request
from opentelemetry import trace

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")
TRACE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def normalize_trace_id(value):
    return value if value and TRACE_RE.fullmatch(value) else uuid.uuid4().hex


def current_trace_id():
    return trace_id_ctx.get()


def current_otel_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}"


@contextmanager
def trace_context(trace_id: str):
    token = trace_id_ctx.set(normalize_trace_id(trace_id))
    try:
        yield
    finally:
        trace_id_ctx.reset(token)


async def tracing_middleware(request: Request, call_next):
    correlation_id = normalize_trace_id(request.headers.get("x-trace-id"))
    token = trace_id_ctx.set(correlation_id)
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("app.correlation_id", correlation_id)
    try:
        response = await call_next(request)
        response.headers["X-Trace-ID"] = correlation_id
        otel_trace_id = current_otel_trace_id()
        if otel_trace_id:
            response.headers["X-OpenTelemetry-Trace-ID"] = otel_trace_id
        return response
    finally:
        trace_id_ctx.reset(token)
