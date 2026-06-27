import json, logging
from datetime import datetime, timezone
from app.core.tracing import current_trace_id

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "account-service",
            "traceId": current_trace_id(),
            "message": record.getMessage(),
        }
        for key in ("eventId", "accountId", "transactionType", "processingStatus", "action", "outcome", "method", "path", "statusCode", "durationMs"):
            if hasattr(record, key): payload[key] = getattr(record, key)
        if record.exc_info: payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)

def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(); handler.setFormatter(JsonFormatter())
    root = logging.getLogger(); root.handlers = [handler]; root.setLevel(level.upper())
