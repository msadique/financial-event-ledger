from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Callable

from prometheus_client import Counter, Gauge
from sqlalchemy.orm import Session

from app.clients.account_service import AccountServiceClient, AccountServiceUnavailable
from app.core.config import Settings, get_settings
from app.core.tracing import trace_context
from app.db.models import Event, PendingDelivery
from app.db.session import SessionLocal
from app.repositories.audit import AuditRepository
from app.repositories.delivery_queue import DeliveryQueueRepository

logger = logging.getLogger(__name__)

QUEUED_EVENTS = Counter(
    "gateway_async_fallback_queued_total",
    "Events placed in the local async fallback queue",
)
PROCESSED_EVENTS = Counter(
    "gateway_async_fallback_processed_total",
    "Queued events successfully applied to the Account Service",
)
RETRY_EVENTS = Counter(
    "gateway_async_fallback_retry_total",
    "Queued delivery attempts that were rescheduled",
)
FAILED_EVENTS = Counter(
    "gateway_async_fallback_failed_total",
    "Queued events permanently rejected by the Account Service",
)
QUEUE_DEPTH = Gauge(
    "gateway_async_fallback_queue_depth",
    "Number of events waiting in the local async fallback queue",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AsyncFallbackWorker:
    def __init__(
        self,
        client: AccountServiceClient,
        settings: Settings | None = None,
        session_factory: Callable[[], Session] = SessionLocal,
    ):
        self.client = client
        self.settings = settings or get_settings()
        self.session_factory = session_factory

    def _backoff_seconds(self, attempt_count: int) -> float:
        exponent = max(0, min(attempt_count - 1, 16))
        base = self.settings.async_fallback_base_backoff_seconds * (2**exponent)
        bounded = min(base, self.settings.async_fallback_max_backoff_seconds)
        jitter = random.uniform(0, self.settings.async_fallback_jitter_seconds)
        return bounded + jitter

    async def process_once(self) -> int:
        with self.session_factory() as db:
            queue = DeliveryQueueRepository(db)
            event_ids = queue.due_event_ids(limit=self.settings.async_fallback_batch_size)
            QUEUE_DEPTH.set(queue.count())

        processed = 0
        for event_id in event_ids:
            if await self._process_event(event_id):
                processed += 1

        with self.session_factory() as db:
            QUEUE_DEPTH.set(DeliveryQueueRepository(db).count())
        return processed

    async def _process_event(self, event_id: str) -> bool:
        with self.session_factory() as db:
            queue = DeliveryQueueRepository(db)
            delivery = queue.get(event_id)
            event = db.get(Event, event_id)
            if delivery is None:
                return False
            if event is None:
                queue.delete(delivery)
                db.commit()
                return False

            with trace_context(delivery.trace_id):
                try:
                    response = await self.client.apply_transaction(delivery.payload_json)
                except AccountServiceUnavailable as exc:
                    delivery.attempt_count += 1
                    delivery.last_error = str(exc)
                    delivery.next_attempt_at = utcnow() + timedelta(
                        seconds=self._backoff_seconds(delivery.attempt_count)
                    )
                    delivery.updated_at = utcnow()
                    AuditRepository(db).record(
                        "EVENT_QUEUE_RETRY_SCHEDULED",
                        "RETRY",
                        event_id=event.event_id,
                        account_id=event.account_id,
                        details={
                            "attempt": delivery.attempt_count,
                            "nextAttemptAt": delivery.next_attempt_at.isoformat(),
                        },
                        commit=False,
                    )
                    db.commit()
                    RETRY_EVENTS.inc()
                    logger.warning(
                        "queued event delivery rescheduled",
                        extra={
                            "eventId": event.event_id,
                            "accountId": event.account_id,
                            "attempt": delivery.attempt_count,
                        },
                    )
                    return False

                if response.status_code >= 400:
                    event.processing_status = "FAILED"
                    event.updated_at = utcnow()
                    queue.delete(delivery)
                    AuditRepository(db).record(
                        "EVENT_QUEUE_REJECTED",
                        "FAILURE",
                        event_id=event.event_id,
                        account_id=event.account_id,
                        details={"downstreamStatus": response.status_code},
                        commit=False,
                    )
                    db.commit()
                    FAILED_EVENTS.inc()
                    logger.error(
                        "queued event permanently rejected",
                        extra={
                            "eventId": event.event_id,
                            "accountId": event.account_id,
                            "statusCode": response.status_code,
                        },
                    )
                    return True

                event.processing_status = "APPLIED"
                event.updated_at = utcnow()
                queue.delete(delivery)
                AuditRepository(db).record(
                    "EVENT_APPLIED_FROM_QUEUE",
                    "SUCCESS",
                    event_id=event.event_id,
                    account_id=event.account_id,
                    details={"attempts": delivery.attempt_count + 1},
                    commit=False,
                )
                db.commit()
                PROCESSED_EVENTS.inc()
                logger.info(
                    "queued event applied successfully",
                    extra={
                        "eventId": event.event_id,
                        "accountId": event.account_id,
                        "attempts": delivery.attempt_count + 1,
                    },
                )
                return True

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("async fallback worker started")
        while not stop_event.is_set():
            try:
                await self.process_once()
            except Exception:
                logger.exception("async fallback worker iteration failed")

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.settings.async_fallback_poll_seconds,
                )
            except TimeoutError:
                pass
        logger.info("async fallback worker stopped")
