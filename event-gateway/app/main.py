import asyncio
import logging
import math
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from app.api.routes_accounts import router as accounts_router
from app.api.routes_audit import router as audit_router
from app.api.routes_events import router as events_router
from app.clients.account_service import get_account_client
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.tracing import current_trace_id, normalize_trace_id, tracing_middleware
from app.db.session import Base, SessionLocal, engine
from app.repositories.delivery_queue import DeliveryQueueRepository
from app.services.async_fallback import AsyncFallbackWorker

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

REQUESTS = Counter(
    "gateway_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "gateway_http_request_duration_seconds",
    "HTTP latency",
    ["method", "path"],
)
RATE_LIMIT_REJECTIONS = Counter(
    "gateway_rate_limit_rejections_total",
    "Requests rejected by the Gateway rate limiter",
    ["path"],
)

app = FastAPI(title="Event Ledger Gateway", version="0.3.0")
install_exception_handlers(app)
app.state.rate_limiter = SlidingWindowRateLimiter(
    settings.rate_limit_requests,
    settings.rate_limit_window_seconds,
)
app.state.async_fallback_task = None
app.state.async_fallback_stop = None


@app.on_event("startup")
async def startup():
    Base.metadata.create_all(engine)
    if settings.async_fallback_enabled and app.state.async_fallback_task is None:
        stop_event = asyncio.Event()
        worker = AsyncFallbackWorker(get_account_client(), settings)
        app.state.async_fallback_stop = stop_event
        app.state.async_fallback_task = asyncio.create_task(worker.run(stop_event))


@app.on_event("shutdown")
async def shutdown():
    stop_event = app.state.async_fallback_stop
    task = app.state.async_fallback_task
    if stop_event is None or task is None:
        return

    stop_event.set()
    try:
        await asyncio.wait_for(
            task,
            timeout=max(2.0, settings.async_fallback_poll_seconds + 1.0),
        )
    except TimeoutError:
        task.cancel()
    finally:
        app.state.async_fallback_task = None
        app.state.async_fallback_stop = None


def _is_rate_limit_exempt(path: str) -> bool:
    return path in {"/health", "/metrics", "/openapi.json"} or path.startswith(
        ("/docs", "/redoc")
    )


def _rate_limit_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return host


@app.middleware("http")
async def metrics_and_access_log(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request error")
        raise

    duration = time.perf_counter() - started
    route = request.scope.get("route")
    template = route.path if route else request.url.path
    REQUESTS.labels(request.method, template, str(response.status_code)).inc()
    LATENCY.labels(request.method, template).observe(duration)
    logger.info(
        "request completed",
        extra={
            "method": request.method,
            "path": template,
            "statusCode": response.status_code,
            "durationMs": round(duration * 1000, 2),
        },
    )
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not settings.rate_limit_enabled or _is_rate_limit_exempt(request.url.path):
        return await call_next(request)

    decision = app.state.rate_limiter.check(_rate_limit_key(request))
    headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_after),
    }

    if not decision.allowed:
        RATE_LIMIT_REJECTIONS.labels(request.url.path).inc()
        headers["Retry-After"] = str(decision.retry_after)
        trace_id = current_trace_id()
        if trace_id == "-":
            trace_id = normalize_trace_id(request.headers.get("x-trace-id"))
        headers["X-Trace-ID"] = trace_id
        return JSONResponse(
            status_code=429,
            headers=headers,
            content={
                "error": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "Too many requests; retry after the indicated delay",
                    "traceId": trace_id,
                    "retryable": True,
                    "details": {"retryAfterSeconds": decision.retry_after},
                }
            },
        )

    response = await call_next(request)
    response.headers.update(headers)
    return response


# Registered after the other middleware so every response, including a 429,
# carries a stable trace identifier.
app.middleware("http")(tracing_middleware)


@app.get("/health")
async def health():
    db_status = "UP"
    downstream = "UP"
    queue_depth = 0
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        db_status = "DOWN"

    if db_status == "UP":
        try:
            with SessionLocal() as db:
                queue_depth = DeliveryQueueRepository(db).count()
        except Exception:
            # Database connectivity is healthy even if an older schema has not
            # yet created the optional queue table. Startup creates it normally.
            queue_depth = 0

    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            response = await client.get(f"{settings.account_service_url}/health")
            downstream = "UP" if response.status_code == 200 else "DOWN"
    except Exception:
        downstream = "DOWN"

    status = "UP" if db_status == "UP" else "DOWN"
    body = {
        "service": settings.service_name,
        "status": status,
        "database": db_status,
        "dependencies": {"accountService": downstream},
        "asyncFallback": {
            "enabled": settings.async_fallback_enabled,
            "queuedEvents": queue_depth,
        },
    }
    return body if status == "UP" else JSONResponse(status_code=503, content=body)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(events_router)
app.include_router(accounts_router)
app.include_router(audit_router)
