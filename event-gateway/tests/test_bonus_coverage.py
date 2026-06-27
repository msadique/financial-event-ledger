from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Request

from app.clients.account_service import AccountServiceClient, AccountServiceUnavailable
from app.core.config import Settings
from app.core.rate_limit import RateLimitDecision, SlidingWindowRateLimiter
from app.db.models import AuditRecord, Event, PendingDelivery
from app.main import (
    app,
    metrics_and_access_log,
    rate_limit_middleware,
    settings,
    shutdown,
    startup,
)
from app.repositories.delivery_queue import DeliveryQueueRepository
from app.services.async_fallback import AsyncFallbackWorker
from tests.conftest import TestingSession


def _event(event_id: str = "evt-queue-coverage") -> Event:
    return Event(
        event_id=event_id,
        account_id="acct-queue-coverage",
        type="CREDIT",
        amount="10.00",
        currency="USD",
        event_timestamp=datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc),
        processing_status="QUEUED",
    )


def _delivery(event_id: str = "evt-queue-coverage") -> PendingDelivery:
    return PendingDelivery(
        event_id=event_id,
        account_id="acct-queue-coverage",
        payload_json={
            "eventId": event_id,
            "accountId": "acct-queue-coverage",
            "type": "CREDIT",
            "amount": "10.00",
            "currency": "USD",
            "eventTimestamp": "2026-06-27T10:00:00+00:00",
        },
        trace_id="queue-coverage-trace",
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )


def _request(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )


def test_rate_limiter_validates_constructor_and_reset(monkeypatch):
    with pytest.raises(ValueError, match="limit must be at least 1"):
        SlidingWindowRateLimiter(limit=0, window_seconds=1)

    with pytest.raises(ValueError, match="window_seconds must be positive"):
        SlidingWindowRateLimiter(limit=1, window_seconds=0)

    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: 50.0)
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=10)
    assert limiter.check("client").allowed is True
    assert limiter.check("client").allowed is False

    limiter.reset()

    assert limiter.check("client").allowed is True


def test_delivery_queue_enqueue_updates_existing_record():
    with TestingSession() as db:
        repository = DeliveryQueueRepository(db)
        original = repository.enqueue(
            event_id="evt-existing",
            account_id="acct-existing",
            payload={"amount": "1.00"},
            trace_id="trace-old",
        )
        db.commit()
        original_next_attempt = original.next_attempt_at

        updated = repository.enqueue(
            event_id="evt-existing",
            account_id="acct-existing",
            payload={"amount": "2.00"},
            trace_id="trace-new",
        )
        db.commit()

        assert updated is original
        assert updated.payload_json == {"amount": "2.00"}
        assert updated.trace_id == "trace-new"
        assert updated.next_attempt_at >= original_next_attempt
        assert repository.count() == 1


@pytest.mark.asyncio
async def test_account_client_zero_attempts_fails_without_calling_transport():
    client = AccountServiceClient(
        settings=Settings(account_service_max_attempts=0),
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("transport must not be called")
        ),
    )

    with pytest.raises(AccountServiceUnavailable, match="None"):
        await client.get_balance("acct-no-attempts")


def test_async_fallback_backoff_is_bounded_and_adds_jitter(monkeypatch):
    worker = AsyncFallbackWorker(
        client=SimpleNamespace(),
        settings=Settings(
            async_fallback_base_backoff_seconds=2,
            async_fallback_max_backoff_seconds=10,
            async_fallback_jitter_seconds=3,
        ),
        session_factory=TestingSession,
    )
    monkeypatch.setattr("app.services.async_fallback.random.uniform", lambda _a, _b: 1.5)

    assert worker._backoff_seconds(1) == 3.5
    assert worker._backoff_seconds(100) == 11.5


@pytest.mark.asyncio
async def test_async_fallback_returns_false_when_delivery_is_missing():
    worker = AsyncFallbackWorker(
        client=SimpleNamespace(),
        settings=Settings(),
        session_factory=TestingSession,
    )

    assert await worker._process_event("missing-delivery") is False


@pytest.mark.asyncio
async def test_async_fallback_deletes_orphan_delivery():
    with TestingSession() as db:
        db.add(_delivery("evt-orphan"))
        db.commit()

    worker = AsyncFallbackWorker(
        client=SimpleNamespace(),
        settings=Settings(),
        session_factory=TestingSession,
    )

    assert await worker._process_event("evt-orphan") is False
    with TestingSession() as db:
        assert db.get(PendingDelivery, "evt-orphan") is None


@pytest.mark.asyncio
async def test_async_fallback_reschedules_unavailable_delivery(monkeypatch):
    class UnavailableClient:
        async def apply_transaction(self, _payload):
            raise AccountServiceUnavailable("still down")

    with TestingSession() as db:
        db.add(_event("evt-retry"))
        db.add(_delivery("evt-retry"))
        db.commit()

    worker = AsyncFallbackWorker(
        client=UnavailableClient(),
        settings=Settings(
            async_fallback_batch_size=5,
            async_fallback_base_backoff_seconds=2,
            async_fallback_max_backoff_seconds=2,
            async_fallback_jitter_seconds=0,
        ),
        session_factory=TestingSession,
    )
    monkeypatch.setattr(worker, "_backoff_seconds", lambda _attempt: 2.0)

    processed = await worker.process_once()

    assert processed == 0
    with TestingSession() as db:
        delivery = db.get(PendingDelivery, "evt-retry")
        event = db.get(Event, "evt-retry")
        audits = list(
            db.query(AuditRecord)
            .filter(AuditRecord.event_id == "evt-retry")
            .all()
        )
        assert delivery is not None
        assert delivery.attempt_count == 1
        assert delivery.last_error == "still down"
        assert delivery.next_attempt_at > datetime.now()
        assert event.processing_status == "QUEUED"
        assert "EVENT_QUEUE_RETRY_SCHEDULED" in [record.action for record in audits]


@pytest.mark.asyncio
async def test_async_fallback_marks_permanent_rejection_failed():
    class RejectingClient:
        async def apply_transaction(self, _payload):
            return httpx.Response(
                409,
                request=httpx.Request("POST", "http://account/transactions"),
                json={"error": {"code": "CONFLICT"}},
            )

    with TestingSession() as db:
        db.add(_event("evt-rejected"))
        db.add(_delivery("evt-rejected"))
        db.commit()

    worker = AsyncFallbackWorker(
        client=RejectingClient(),
        settings=Settings(),
        session_factory=TestingSession,
    )

    assert await worker._process_event("evt-rejected") is True
    with TestingSession() as db:
        event = db.get(Event, "evt-rejected")
        audits = list(
            db.query(AuditRecord)
            .filter(AuditRecord.event_id == "evt-rejected")
            .all()
        )
        assert event.processing_status == "FAILED"
        assert db.get(PendingDelivery, "evt-rejected") is None
        assert "EVENT_QUEUE_REJECTED" in [record.action for record in audits]


@pytest.mark.asyncio
async def test_async_fallback_run_recovers_from_iteration_error_and_stops():
    worker = AsyncFallbackWorker(
        client=SimpleNamespace(),
        settings=Settings(async_fallback_poll_seconds=0.001),
        session_factory=TestingSession,
    )
    stop_event = asyncio.Event()
    calls = {"count": 0}

    async def process_once():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary worker failure")
        stop_event.set()
        return 0

    worker.process_once = process_once

    await worker.run(stop_event)

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_startup_creates_worker_task(monkeypatch):
    created = {}

    class FakeWorker:
        def __init__(self, client, configured_settings):
            created["client"] = client
            created["settings"] = configured_settings

        async def run(self, _stop_event):
            return None

    class FakeTask:
        pass

    def fake_create_task(coro):
        created["coro"] = coro
        coro.close()
        return FakeTask()

    monkeypatch.setattr(settings, "async_fallback_enabled", True)
    monkeypatch.setattr("app.main.Base.metadata.create_all", lambda _engine: created.setdefault("schema", True))
    monkeypatch.setattr("app.main.get_account_client", lambda: "client")
    monkeypatch.setattr("app.main.AsyncFallbackWorker", FakeWorker)
    monkeypatch.setattr("app.main.asyncio.create_task", fake_create_task)
    app.state.async_fallback_task = None
    app.state.async_fallback_stop = None

    await startup()

    assert created["schema"] is True
    assert created["client"] == "client"
    assert created["settings"] is settings
    assert app.state.async_fallback_task is not None
    assert isinstance(app.state.async_fallback_stop, asyncio.Event)

    app.state.async_fallback_task = None
    app.state.async_fallback_stop = None


@pytest.mark.asyncio
async def test_startup_does_not_replace_existing_task(monkeypatch):
    sentinel = object()
    app.state.async_fallback_task = sentinel
    monkeypatch.setattr(settings, "async_fallback_enabled", True)
    monkeypatch.setattr("app.main.Base.metadata.create_all", lambda _engine: None)
    monkeypatch.setattr(
        "app.main.AsyncFallbackWorker",
        lambda *_args, **_kwargs: pytest.fail("worker should not be created"),
    )

    await startup()

    assert app.state.async_fallback_task is sentinel
    app.state.async_fallback_task = None
    app.state.async_fallback_stop = None


@pytest.mark.asyncio
async def test_shutdown_without_worker_returns_cleanly():
    app.state.async_fallback_stop = None
    app.state.async_fallback_task = None
    await shutdown()


@pytest.mark.asyncio
async def test_shutdown_waits_for_worker_and_clears_state():
    stop_event = asyncio.Event()
    task = asyncio.create_task(asyncio.sleep(0))
    app.state.async_fallback_stop = stop_event
    app.state.async_fallback_task = task

    await shutdown()

    assert stop_event.is_set()
    assert app.state.async_fallback_stop is None
    assert app.state.async_fallback_task is None


@pytest.mark.asyncio
async def test_shutdown_cancels_worker_after_timeout(monkeypatch):
    class FakeTask:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    fake_task = FakeTask()
    app.state.async_fallback_stop = asyncio.Event()
    app.state.async_fallback_task = fake_task

    async def raise_timeout(_task, timeout):
        assert timeout >= 2
        raise TimeoutError

    monkeypatch.setattr("app.main.asyncio.wait_for", raise_timeout)

    await shutdown()

    assert fake_task.cancelled is True
    assert app.state.async_fallback_stop is None
    assert app.state.async_fallback_task is None


@pytest.mark.asyncio
async def test_metrics_middleware_reraises_application_exception():
    request = _request("/boom")

    async def failing_call_next(_request):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await metrics_and_access_log(request, failing_call_next)


@pytest.mark.asyncio
async def test_rate_limit_middleware_creates_trace_when_context_is_empty(monkeypatch):
    class RejectingLimiter:
        def check(self, _key):
            return RateLimitDecision(
                allowed=False,
                limit=1,
                remaining=0,
                retry_after=7,
                reset_after=7,
            )

    original_limiter = app.state.rate_limiter
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    app.state.rate_limiter = RejectingLimiter()
    request = _request(
        "/events/limited",
        headers=[(b"x-trace-id", b"direct-rate-limit-trace")],
    )

    async def unexpected_call_next(_request):
        pytest.fail("blocked request must not reach the application")

    try:
        response = await rate_limit_middleware(request, unexpected_call_next)
    finally:
        app.state.rate_limiter = original_limiter

    assert response.status_code == 429
    assert response.headers["X-Trace-ID"] == "direct-rate-limit-trace"
    assert response.headers["Retry-After"] == "7"


def test_event_schema_rejects_non_alpha_currency_and_naive_timestamp():
    from pydantic import ValidationError

    from app.schemas.events import EventCreate

    base = {
        "eventId": "evt-schema-coverage",
        "accountId": "acct-schema-coverage",
        "type": "CREDIT",
        "amount": "1.00",
        "currency": "USD",
        "eventTimestamp": "2026-06-27T10:00:00Z",
    }

    with pytest.raises(ValidationError, match="currency must contain three letters"):
        EventCreate(**{**base, "currency": "U1D"})

    with pytest.raises(ValidationError, match="eventTimestamp must include timezone"):
        EventCreate(**{**base, "eventTimestamp": "2026-06-27T10:00:00"})
