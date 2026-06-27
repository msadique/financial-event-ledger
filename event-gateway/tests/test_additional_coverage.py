from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.clients.account_service import (
    AccountServiceClient,
    AccountServiceUnavailable,
    CircuitBreaker,
)
from app.core.config import Settings
from app.core.errors import error_body, install_exception_handlers
from app.core.tracing import trace_id_ctx
from app.db.session import get_db
from app.main import app, health, metrics


@pytest.mark.asyncio
async def test_downstream_client_retries_transient_response_then_succeeds(monkeypatch):
    calls = {"count": 0}

    async def handler(request: httpx.Request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, request=request, json={"error": {"message": "busy"}})
        return httpx.Response(200, request=request, json={"balance": "10.0000"})

    monkeypatch.setattr("app.clients.account_service.asyncio.sleep", lambda _: _completed())
    monkeypatch.setattr("app.clients.account_service.random.uniform", lambda *_: 0)
    client = AccountServiceClient(
        settings=Settings(
            account_service_url="http://account-service",
            account_service_max_attempts=2,
            account_service_timeout_seconds=1,
            circuit_breaker_failure_threshold=5,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = await client.get_balance("acct-1")

    assert response.status_code == 200
    assert calls["count"] == 2
    assert client.breaker.failures == 0


async def _completed():
    return None


@pytest.mark.asyncio
async def test_downstream_client_exhausts_retries_and_opens_circuit(monkeypatch):
    calls = {"count": 0}

    async def handler(request: httpx.Request):
        calls["count"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    async def no_sleep(_):
        return None

    monkeypatch.setattr("app.clients.account_service.asyncio.sleep", no_sleep)
    monkeypatch.setattr("app.clients.account_service.random.uniform", lambda *_: 0)
    client = AccountServiceClient(
        settings=Settings(
            account_service_url="http://account-service",
            account_service_max_attempts=2,
            account_service_timeout_seconds=1,
            circuit_breaker_failure_threshold=2,
            circuit_breaker_recovery_seconds=30,
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AccountServiceUnavailable, match="connection refused"):
        await client.get_balance("acct-1")

    assert calls["count"] == 2
    assert client.breaker.opened_at is not None


@pytest.mark.asyncio
async def test_non_retryable_downstream_response_is_returned_without_retry():
    calls = {"count": 0}

    async def handler(request: httpx.Request):
        calls["count"] += 1
        return httpx.Response(409, request=request, json={"error": {"code": "CONFLICT"}})

    client = AccountServiceClient(
        settings=Settings(
            account_service_url="http://account-service",
            account_service_max_attempts=3,
            account_service_timeout_seconds=1,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = await client.apply_transaction({"accountId": "acct-1"})

    assert response.status_code == 409
    assert calls["count"] == 1


def test_circuit_breaker_failure_below_threshold_stays_closed(monkeypatch):
    monkeypatch.setattr("app.clients.account_service.time.monotonic", lambda: 10.0)
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=30)

    breaker.failure()
    breaker.allow()

    assert breaker.failures == 1
    assert breaker.opened_at is None


def test_error_body_includes_optional_details():
    token = trace_id_ctx.set("coverage-trace")
    try:
        body = error_body("BAD_INPUT", "bad", retryable=True, details={"field": "amount"})
    finally:
        trace_id_ctx.reset(token)

    assert body["error"] == {
        "code": "BAD_INPUT",
        "message": "bad",
        "traceId": "coverage-trace",
        "retryable": True,
        "details": {"field": "amount"},
    }


def test_exception_handlers_cover_string_database_and_generic_errors():
    test_app = FastAPI()
    install_exception_handlers(test_app)

    @test_app.get("/http")
    def http_failure():
        raise HTTPException(418, detail="teapot", headers={"X-Test": "yes"})

    @test_app.get("/database")
    def database_failure():
        raise SQLAlchemyError("database down")

    @test_app.get("/generic")
    def generic_failure():
        raise RuntimeError("boom")

    with TestClient(test_app, raise_server_exceptions=False) as client:
        http_response = client.get("/http")
        database_response = client.get("/database")
        generic_response = client.get("/generic")

    assert http_response.status_code == 418
    assert http_response.headers["X-Test"] == "yes"
    assert http_response.json()["error"]["code"] == "HTTP_ERROR"
    assert database_response.status_code == 503
    assert database_response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert database_response.json()["error"]["retryable"] is True
    assert generic_response.status_code == 500
    assert generic_response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_get_db_closes_session(monkeypatch):
    closed = {"value": False}

    class FakeSession:
        def close(self):
            closed["value"] = True

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: FakeSession())
    dependency = get_db()

    assert isinstance(next(dependency), FakeSession)
    dependency.close()
    assert closed["value"] is True


@pytest.mark.asyncio
async def test_health_reports_downstream_down_but_gateway_up(monkeypatch):
    class FakeResponse:
        status_code = 503

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _url):
            return FakeResponse()

    monkeypatch.setattr("app.main.httpx.AsyncClient", FakeAsyncClient)
    result = await health()

    assert result["status"] == "UP"
    assert result["dependencies"]["accountService"] == "DOWN"


@pytest.mark.asyncio
async def test_health_reports_gateway_database_down(monkeypatch):
    @contextmanager
    def broken_session():
        raise RuntimeError("database down")
        yield

    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("down")

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("app.main.SessionLocal", broken_session)
    monkeypatch.setattr("app.main.httpx.AsyncClient", FailingAsyncClient)
    result = await health()

    assert result.status_code == 503
    assert b'"database":"DOWN"' in result.body
    assert b'"accountService":"DOWN"' in result.body


def test_metrics_endpoint_returns_prometheus_payload():
    response = metrics()
    assert response.status_code == 200
    assert "text/plain" in response.media_type
    assert b"gateway_http_requests_total" in response.body


def test_balance_proxy_returns_downstream_payload(client):
    class BalanceClient:
        async def get_balance(self, account_id):
            return httpx.Response(
                200,
                request=httpx.Request("GET", f"http://account/{account_id}"),
                json={"accountId": account_id, "balance": "42.0000", "currency": "USD"},
            )

    from app.clients.account_service import get_account_client

    app.dependency_overrides[get_account_client] = lambda: BalanceClient()
    try:
        response = client.get("/accounts/acct-balance/balance")
    finally:
        app.dependency_overrides.pop(get_account_client, None)

    assert response.status_code == 200
    assert response.json()["balance"] == "42.0000"


def test_downstream_business_error_marks_event_failed_and_is_audited(client):
    class RejectingClient:
        async def apply_transaction(self, _payload):
            return httpx.Response(
                409,
                request=httpx.Request("POST", "http://account/transactions"),
                json={"error": {"code": "CURRENCY_MISMATCH", "message": "wrong currency"}},
            )

        async def get_balance(self, _account_id):
            raise AssertionError("not expected")

    from app.clients.account_service import get_account_client

    payload = {
        "eventId": "evt-downstream-reject",
        "accountId": "acct-downstream-reject",
        "type": "CREDIT",
        "amount": "10.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }
    app.dependency_overrides[get_account_client] = lambda: RejectingClient()
    try:
        response = client.post("/events", json=payload)
        stored = client.get("/events/evt-downstream-reject")
        audits = client.get("/audit/events/evt-downstream-reject").json()
    finally:
        app.dependency_overrides.pop(get_account_client, None)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CURRENCY_MISMATCH"
    assert stored.json()["processingStatus"] == "FAILED"
    assert "EVENT_PROCESSING_FAILED" in [item["action"] for item in audits]


@pytest.mark.asyncio
async def test_event_service_integrity_error_replay_branch():
    from datetime import datetime, timezone
    from decimal import Decimal
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError

    from app.schemas.events import EventCreate
    from app.services.event_service import EventService

    command = EventCreate(
        eventId="evt-race-replay",
        accountId="acct-race",
        type="CREDIT",
        amount="5.00",
        currency="USD",
        eventTimestamp="2026-05-15T14:02:11Z",
    )
    existing = SimpleNamespace(
        event_id=command.event_id,
        account_id=command.account_id,
        type=command.type.value,
        amount=Decimal("5.00"),
        currency="USD",
        event_timestamp=command.event_timestamp.replace(tzinfo=None),
        metadata_json=None,
        processing_status="APPLIED",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class FakeDB:
        def rollback(self):
            pass

    service = EventService(FakeDB(), SimpleNamespace())
    get_calls = {"count": 0}

    def get_event(_event_id):
        get_calls["count"] += 1
        return None if get_calls["count"] == 1 else existing

    service.repo = SimpleNamespace(
        get=get_event,
        add=lambda _event: (_ for _ in ()).throw(IntegrityError("insert", {}, Exception("duplicate"))),
    )
    service.audit = SimpleNamespace(record=lambda *args, **kwargs: None)

    event, created = await service.submit(command)

    assert event is existing
    assert created is False


@pytest.mark.asyncio
async def test_event_service_integrity_error_conflict_branch():
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError

    from app.schemas.events import EventCreate
    from app.services.event_service import EventService

    command = EventCreate(
        eventId="evt-race-conflict",
        accountId="acct-race",
        type="CREDIT",
        amount="5.00",
        currency="USD",
        eventTimestamp="2026-05-15T14:02:11Z",
    )

    class FakeDB:
        def rollback(self):
            pass

    service = EventService(FakeDB(), SimpleNamespace())
    get_calls = {"count": 0}

    def get_event(_event_id):
        get_calls["count"] += 1
        return None

    service.repo = SimpleNamespace(
        get=get_event,
        add=lambda _event: (_ for _ in ()).throw(IntegrityError("insert", {}, Exception("duplicate"))),
    )
    service.audit = SimpleNamespace(record=lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        await service.submit(command)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "EVENT_ID_CONFLICT"


def test_audit_repository_without_immediate_commit():
    from app.repositories.audit import AuditRepository

    class FakeDB:
        def __init__(self):
            self.added = []
            self.commits = 0
            self.refreshes = 0

        def add(self, value):
            self.added.append(value)

        def commit(self):
            self.commits += 1

        def refresh(self, _value):
            self.refreshes += 1

    db = FakeDB()
    record = AuditRepository(db).record("TEST_ACTION", "SUCCESS", commit=False)

    assert record.action == "TEST_ACTION"
    assert db.added == [record]
    assert db.commits == 0
    assert db.refreshes == 0
