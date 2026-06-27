import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from app.core.tracing import current_trace_id

logger = logging.getLogger(__name__)


def error_body(code: str, message: str, *, retryable: bool = False, details=None) -> dict:
    error = {
        "code": code,
        "message": message,
        "traceId": current_trace_id(),
        "retryable": retryable,
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(part) for part in item["loc"] if part != "body"), "reason": item["msg"]}
            for item in exc.errors()
        ]
        return JSONResponse(content=error_body("VALIDATION_ERROR", "Request validation failed", details=details), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", "HTTP_ERROR")
            message = detail.get("message", "Request failed")
            retryable = bool(detail.get("retryable", False))
            details = detail.get("details")
        else:
            code, message, retryable, details = "HTTP_ERROR", str(detail), False, None
        return JSONResponse(content=error_body(code, message, retryable=retryable, details=details), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_: Request, exc: SQLAlchemyError):
        logger.exception("Database operation failed", exc_info=exc)
        return JSONResponse(content=error_body("DATABASE_UNAVAILABLE", "Database operation failed", retryable=True), status_code=503)

    @app.exception_handler(Exception)
    async def generic_error(_: Request, exc: Exception):
        logger.exception("Unhandled exception", exc_info=exc)
        return JSONResponse(content=error_body("INTERNAL_ERROR", "Unexpected internal error"), status_code=500)
