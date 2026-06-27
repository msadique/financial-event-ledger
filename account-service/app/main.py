import logging, time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text
from app.api.routes_accounts import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tracing import current_trace_id, tracing_middleware
from app.db.session import Base, SessionLocal, engine

settings=get_settings(); configure_logging(settings.log_level); logger=logging.getLogger(__name__)
REQUESTS=Counter("account_http_requests_total", "HTTP requests", ["method","path","status"])
LATENCY=Histogram("account_http_request_duration_seconds", "HTTP latency", ["method","path"])
app=FastAPI(title="Event Ledger Account Service", version="0.1.0")
app.middleware("http")(tracing_middleware)

@app.on_event("startup")
def startup(): Base.metadata.create_all(engine)

@app.middleware("http")
async def metrics_and_access_log(request: Request, call_next):
    started=time.perf_counter()
    try: response=await call_next(request)
    except Exception:
        logger.exception("Unhandled request error"); raise
    duration=time.perf_counter()-started
    template=request.scope.get("route").path if request.scope.get("route") else request.url.path
    REQUESTS.labels(request.method, template, str(response.status_code)).inc(); LATENCY.labels(request.method, template).observe(duration)
    logger.info("request completed", extra={"method":request.method,"path":template,"statusCode":response.status_code,"durationMs":round(duration*1000,2)})
    return response

@app.exception_handler(Exception)
async def generic_error(request, exc):
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"error":{"code":"INTERNAL_ERROR","message":"unexpected internal error","traceId":current_trace_id()}})

@app.get("/health")
def health():
    try:
        with SessionLocal() as db: db.execute(text("SELECT 1"))
        return {"service":settings.service_name,"status":"UP","database":"UP"}
    except Exception:
        return JSONResponse(status_code=503, content={"service":settings.service_name,"status":"DOWN","database":"DOWN"})

@app.get("/metrics", include_in_schema=False)
def metrics(): return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

app.include_router(router)
