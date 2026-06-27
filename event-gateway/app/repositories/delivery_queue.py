from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PendingDelivery


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeliveryQueueRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, event_id: str) -> PendingDelivery | None:
        return self.db.get(PendingDelivery, event_id)

    def enqueue(
        self,
        *,
        event_id: str,
        account_id: str,
        payload: dict,
        trace_id: str,
    ) -> PendingDelivery:
        existing = self.get(event_id)
        if existing:
            existing.payload_json = payload
            existing.trace_id = trace_id
            existing.next_attempt_at = utcnow()
            existing.updated_at = utcnow()
            return existing

        delivery = PendingDelivery(
            event_id=event_id,
            account_id=account_id,
            payload_json=payload,
            trace_id=trace_id,
            next_attempt_at=utcnow(),
        )
        self.db.add(delivery)
        return delivery

    def due_event_ids(self, *, limit: int, now: datetime | None = None) -> list[str]:
        current = now or utcnow()
        statement = (
            select(PendingDelivery.event_id)
            .where(PendingDelivery.next_attempt_at <= current)
            .order_by(PendingDelivery.next_attempt_at.asc(), PendingDelivery.event_id.asc())
            .limit(limit)
        )
        return list(self.db.scalars(statement))

    def delete(self, delivery: PendingDelivery) -> None:
        self.db.delete(delivery)

    def count(self) -> int:
        return len(list(self.db.scalars(select(PendingDelivery.event_id))))
