from __future__ import annotations

import httpx
import pytest

from app.clients.account_service import AccountServiceUnavailable, get_account_client
from app.core.config import Settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db.models import Event, PendingDelivery
from app.main import app, settings
from app.services.async_fallback import AsyncFallbackWorker
from tests.conftest import TestingSession

BASE = {
    "eventId": "evt-queued-1",
    "accountId": "acct-queued-1",
    "type": "CREDIT",
    "amount": "25.00",
    "currency": "USD",
    "eventTimestamp": "2026-06-27T10:00:00Z",
}


class FailingClient:
    async def apply_transaction(self, _payload):
        raise AccountServiceUnavailable("down")

    async def get_balance(self, _account_id):
        raise AccountServiceUnavailable("down")


class RecoveringClient:
    async def apply_transaction(self, payload):
        return httpx.Response(
            200,
            request=httpx.Request(
                "POST",
                f"http://account/{payload['accountId']}/transactions",
            ),
            json={"applied": True, "idempotentReplay": False},
        )


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_rejects_and_recovers():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)

    first = limiter.check("client", now=100)
    second = limiter.check("client", now=101)
    blocked = limiter.check("client", now=102)
    recovered = limiter.check("client", now=111)

    assert first.allowed is True
    assert second.allowed is True
    assert blocked.allowed is False
    assert blocked.retry_after == 8
    assert recovered.allowed is True


def test_gateway_rate_limit_returns_structured_429(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    original = app.state.rate_limiter
    app.state.rate_limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    try:
        assert client.get("/events/missing-1").status_code == 404
        assert client.get("/events/missing-2").status_code == 404
        response = client.get(
            "/events/missing-3",
            headers={"X-Trace-ID": "rate-limit-trace"},
        )
    finally:
        app.state.rate_limiter = original

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert response.json()["error"]["traceId"] == "rate-limit-trace"
    assert response.headers["Retry-After"]
    assert response.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_failed_delivery_is_queued_and_applied_after_recovery(
    client,
    monkeypatch,
):
    queued_settings = Settings(
        database_url="sqlite:///:memory:",
        async_fallback_enabled=True,
        async_fallback_poll_seconds=0.01,
        async_fallback_base_backoff_seconds=0.01,
        async_fallback_max_backoff_seconds=0.01,
        async_fallback_jitter_seconds=0,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr(
        "app.services.event_service.get_settings",
        lambda: queued_settings,
    )
    app.dependency_overrides[get_account_client] = lambda: FailingClient()
    try:
        response = client.post(
            "/events",
            json=BASE,
            headers={"X-Trace-ID": "queued-trace"},
        )
    finally:
        app.dependency_overrides.pop(get_account_client, None)

    assert response.status_code == 202
    assert response.json()["processingStatus"] == "QUEUED"

    with TestingSession() as db:
        assert db.get(PendingDelivery, BASE["eventId"]) is not None

    worker = AsyncFallbackWorker(
        RecoveringClient(),
        queued_settings,
        session_factory=TestingSession,
    )
    processed = await worker.process_once()

    assert processed == 1
    db = TestingSession()
    try:
        event = db.get(Event, BASE["eventId"])
        assert event.processing_status == "APPLIED"
        assert db.get(PendingDelivery, BASE["eventId"]) is None
    finally:
        db.close()
