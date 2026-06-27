import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clients.account_service import AccountServiceClient, AccountServiceUnavailable
from app.core.config import get_settings
from app.core.tracing import current_trace_id
from app.db.models import Event
from app.repositories.audit import AuditRepository
from app.repositories.delivery_queue import DeliveryQueueRepository
from app.repositories.events import EventRepository
from app.schemas.events import EventCreate
from app.services.async_fallback import QUEUED_EVENTS

logger = logging.getLogger(__name__)


def _utc_naive(value):
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def same_event(event: Event, command: EventCreate):
    return (
        event.account_id == command.account_id
        and event.type == command.type.value
        and Decimal(event.amount) == command.amount
        and event.currency == command.currency
        and _utc_naive(event.event_timestamp) == _utc_naive(command.event_timestamp)
        and (event.metadata_json or None) == command.metadata
    )


class EventService:
    def __init__(self, db: Session, client: AccountServiceClient):
        self.db = db
        self.repo = EventRepository(db)
        self.audit = AuditRepository(db)
        self.queue = DeliveryQueueRepository(db)
        self.client = client
        self.settings = get_settings()

    async def submit(self, command: EventCreate):
        logger.info(
            "event received",
            extra={"eventId": command.event_id, "accountId": command.account_id},
        )
        existing = self.repo.get(command.event_id)
        if existing:
            if not same_event(existing, command):
                self.audit.record(
                    "EVENT_CONFLICT_REJECTED",
                    "FAILURE",
                    event_id=command.event_id,
                    account_id=command.account_id,
                    details={"reason": "eventId already exists with different event data"},
                )
                logger.warning(
                    "conflicting event rejected",
                    extra={"eventId": command.event_id, "accountId": command.account_id},
                )
                raise HTTPException(
                    409,
                    detail={
                        "code": "EVENT_ID_CONFLICT",
                        "message": "eventId already exists with different event data",
                    },
                )
            self.audit.record(
                "EVENT_REPLAYED",
                "REPLAY",
                event_id=command.event_id,
                account_id=command.account_id,
            )
            logger.info(
                "event replayed",
                extra={"eventId": command.event_id, "accountId": command.account_id},
            )
            return existing, False

        event = Event(
            event_id=command.event_id,
            account_id=command.account_id,
            type=command.type.value,
            amount=command.amount,
            currency=command.currency,
            event_timestamp=command.event_timestamp,
            metadata_json=command.metadata,
            processing_status="PENDING",
        )
        try:
            self.repo.add(event)
            self.audit.record(
                "EVENT_STORED",
                "SUCCESS",
                event_id=command.event_id,
                account_id=command.account_id,
            )
        except IntegrityError:
            self.db.rollback()
            existing = self.repo.get(command.event_id)
            if existing and same_event(existing, command):
                self.audit.record(
                    "EVENT_REPLAYED",
                    "REPLAY",
                    event_id=command.event_id,
                    account_id=command.account_id,
                )
                return existing, False
            self.audit.record(
                "EVENT_CONFLICT_REJECTED",
                "FAILURE",
                event_id=command.event_id,
                account_id=command.account_id,
            )
            raise HTTPException(
                409,
                detail={
                    "code": "EVENT_ID_CONFLICT",
                    "message": "eventId already exists",
                },
            )

        payload = {
            "eventId": command.event_id,
            "accountId": command.account_id,
            "type": command.type.value,
            "amount": str(command.amount),
            "currency": command.currency,
            "eventTimestamp": command.event_timestamp.isoformat(),
        }
        try:
            response = await self.client.apply_transaction(payload)
            if response.status_code >= 400:
                event.processing_status = "FAILED"
                event.updated_at = datetime.now(timezone.utc)
                self.repo.save(event)
                detail = (
                    response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else {"message": response.text}
                )
                self.audit.record(
                    "EVENT_PROCESSING_FAILED",
                    "FAILURE",
                    event_id=command.event_id,
                    account_id=command.account_id,
                    details={"downstreamStatus": response.status_code},
                )
                logger.error(
                    "downstream rejected event",
                    extra={
                        "eventId": command.event_id,
                        "accountId": command.account_id,
                        "statusCode": response.status_code,
                    },
                )
                raise HTTPException(
                    response.status_code,
                    detail=detail.get("error", detail),
                )
            event.processing_status = "APPLIED"
        except AccountServiceUnavailable:
            if self.settings.async_fallback_enabled:
                event.processing_status = "QUEUED"
                event.updated_at = datetime.now(timezone.utc)
                self.queue.enqueue(
                    event_id=command.event_id,
                    account_id=command.account_id,
                    payload=payload,
                    trace_id=current_trace_id(),
                )
                self.audit.record(
                    "EVENT_QUEUED",
                    "QUEUED",
                    event_id=command.event_id,
                    account_id=command.account_id,
                    details={"reason": "account service unavailable"},
                    commit=False,
                )
                self.db.add(event)
                self.db.commit()
                self.db.refresh(event)
                QUEUED_EVENTS.inc()
                logger.warning(
                    "account service unavailable; event queued",
                    extra={
                        "eventId": command.event_id,
                        "accountId": command.account_id,
                    },
                )
                return event, True

            event.processing_status = "FAILED"
            event.updated_at = datetime.now(timezone.utc)
            self.repo.save(event)
            self.audit.record(
                "EVENT_PROCESSING_FAILED",
                "FAILURE",
                event_id=command.event_id,
                account_id=command.account_id,
                details={"reason": "account service unavailable"},
            )
            logger.error(
                "account service unavailable",
                extra={"eventId": command.event_id, "accountId": command.account_id},
            )
            raise HTTPException(
                503,
                detail={
                    "code": "ACCOUNT_SERVICE_UNAVAILABLE",
                    "message": "Account processing is temporarily unavailable",
                    "retryable": True,
                },
            )

        event.updated_at = datetime.now(timezone.utc)
        self.repo.save(event)
        self.audit.record(
            "EVENT_APPLIED",
            "SUCCESS",
            event_id=command.event_id,
            account_id=command.account_id,
        )
        logger.info(
            "event applied successfully",
            extra={"eventId": command.event_id, "accountId": command.account_id},
        )
        return event, True
