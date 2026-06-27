from contextvars import ContextVar
import re, uuid
from fastapi import Request

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")
TRACE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

def normalize_trace_id(value: str | None) -> str:
    if value and TRACE_RE.fullmatch(value):
        return value
    return uuid.uuid4().hex

def current_trace_id() -> str:
    return trace_id_ctx.get()

async def tracing_middleware(request: Request, call_next):
    trace_id = normalize_trace_id(request.headers.get("x-trace-id"))
    token = trace_id_ctx.set(trace_id)
    try:
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        trace_id_ctx.reset(token)
