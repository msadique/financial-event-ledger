import logging,time
import httpx
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,Response
from prometheus_client import CONTENT_TYPE_LATEST,Counter,Histogram,generate_latest
from sqlalchemy import text
from app.api.routes_accounts import router as accounts_router
from app.api.routes_events import router as events_router
from app.api.routes_audit import router as audit_router
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.core.tracing import current_trace_id,tracing_middleware
from app.db.session import Base,SessionLocal,engine
settings=get_settings(); configure_logging(settings.log_level); logger=logging.getLogger(__name__)
REQUESTS=Counter("gateway_http_requests_total","HTTP requests",["method","path","status"])
LATENCY=Histogram("gateway_http_request_duration_seconds","HTTP latency",["method","path"])
app=FastAPI(title="Event Ledger Gateway",version="0.2.0"); app.middleware("http")(tracing_middleware); install_exception_handlers(app)
@app.on_event("startup")
def startup(): Base.metadata.create_all(engine)
@app.middleware("http")
async def metrics_and_access_log(request:Request,call_next):
    started=time.perf_counter()
    try: response=await call_next(request)
    except Exception: logger.exception("Unhandled request error"); raise
    duration=time.perf_counter()-started; template=request.scope.get("route").path if request.scope.get("route") else request.url.path
    REQUESTS.labels(request.method,template,str(response.status_code)).inc(); LATENCY.labels(request.method,template).observe(duration)
    logger.info("request completed",extra={"method":request.method,"path":template,"statusCode":response.status_code,"durationMs":round(duration*1000,2)})
    return response
@app.get("/health")
async def health():
    db_status="UP"; downstream="UP"
    try:
        with SessionLocal() as db: db.execute(text("SELECT 1"))
    except Exception: db_status="DOWN"
    try:
        async with httpx.AsyncClient(timeout=0.5) as client: r=await client.get(f"{settings.account_service_url}/health"); downstream="UP" if r.status_code==200 else "DOWN"
    except Exception: downstream="DOWN"
    status="UP" if db_status=="UP" else "DOWN"; body={"service":settings.service_name,"status":status,"database":db_status,"dependencies":{"accountService":downstream}}
    return body if status=="UP" else JSONResponse(status_code=503,content=body)
@app.get("/metrics",include_in_schema=False)
def metrics(): return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)
app.include_router(events_router); app.include_router(accounts_router); app.include_router(audit_router)
