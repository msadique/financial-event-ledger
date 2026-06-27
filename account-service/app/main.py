import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from app.api.routes_accounts import router
from app.api.routes_audit import router as audit_router
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.core.telemetry import configure_telemetry, shutdown_telemetry
from app.core.tracing import tracing_middleware
from app.db.session import Base, SessionLocal, engine

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
REQUESTS = Counter("account_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("account_http_request_duration_seconds", "HTTP latency", ["method", "path"])

app = FastAPI(title="Event Ledger Account Service", version="0.4.0")
app.middleware("http")(tracing_middleware)
install_exception_handlers(app)
app.state.otel_tracer_provider = None


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)


@app.on_event("shutdown")
def shutdown():
    shutdown_telemetry(app.state.otel_tracer_provider)


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


@app.get("/health")
def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"service": settings.service_name, "status": "UP", "database": "UP"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"service": settings.service_name, "status": "DOWN", "database": "DOWN"},
        )


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(router)
app.include_router(audit_router)

app.state.otel_tracer_provider = configure_telemetry(app, settings)
