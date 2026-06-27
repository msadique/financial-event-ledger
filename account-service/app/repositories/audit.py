from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.tracing import current_trace_id
from app.db.models import AuditRecord


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def record(self, action: str, outcome: str, *, event_id=None, account_id=None, details=None, commit=True):
        record = AuditRecord(
            action=action,
            outcome=outcome,
            trace_id=current_trace_id(),
            event_id=event_id,
            account_id=account_id,
            details_json=details,
        )
        self.db.add(record)
        if commit:
            self.db.commit()
            self.db.refresh(record)
        return record

    def for_event(self, event_id: str):
        return list(self.db.scalars(select(AuditRecord).where(AuditRecord.event_id == event_id).order_by(AuditRecord.created_at)))
