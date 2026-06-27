import json, logging
from datetime import datetime, timezone
from app.core.tracing import current_trace_id
class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload={"timestamp":datetime.now(timezone.utc).isoformat(),"level":record.levelname,"service":"event-gateway","traceId":current_trace_id(),"message":record.getMessage()}
        for key in ("eventId","accountId","method","path","statusCode","durationMs"):
            if hasattr(record,key): payload[key]=getattr(record,key)
        if record.exc_info: payload["exception"]=self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
def configure_logging(level="INFO"):
    h=logging.StreamHandler(); h.setFormatter(JsonFormatter()); root=logging.getLogger(); root.handlers=[h]; root.setLevel(level.upper())
