from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.errors import error_body, install_exception_handlers
from app.core.tracing import trace_id_ctx
from app.db.session import get_db
from app.main import health, metrics
from app.schemas.accounts import TransactionCreate
from app.services.account_service import AccountService, same_transaction

BASE = {
    "eventId": "evt-extra",
    "accountId": "acct-extra",
    "type": "CREDIT",
    "amount": "10.00",
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z",
}


def test_account_id_mismatch_is_rejected_and_audited(client):
    response = client.post("/accounts/different/transactions", json=BASE)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACCOUNT_ID_MISMATCH"
    audits = client.get("/audit/events/evt-extra").json()
    assert audits[0]["action"] == "TRANSACTION_REJECTED"
    assert audits[0]["details"]["reason"] == "account id mismatch"


def test_unknown_account_endpoints_return_standard_404(client):
    balance = client.get("/accounts/missing/balance")
    details = client.get("/accounts/missing")

    assert balance.status_code == 404
    assert balance.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert details.status_code == 404
    assert details.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_negative_balance_is_supported(client):
    debit = {**BASE, "type": "DEBIT", "amount": "25.00"}
    response = client.post("/accounts/acct-extra/transactions", json=debit)

    assert response.status_code == 201
    assert response.json()["balance"] == "-25.0000"


def test_naive_timestamp_comparison_branch():
    timestamp = datetime(2026, 5, 15, 14, 2, 11)
    tx = SimpleNamespace(
        account_id="acct-extra",
        type="CREDIT",
        amount=Decimal("10.00"),
        currency="USD",
        event_timestamp=timestamp,
    )
    command = TransactionCreate(**{**BASE, "eventTimestamp": timestamp.replace(tzinfo=timezone.utc).isoformat()})

    assert same_transaction(tx, command) is True


def test_error_body_and_all_exception_handler_branches():
    token = trace_id_ctx.set("account-coverage-trace")
    try:
        body = error_body("TEST", "message", retryable=True, details=[{"x": 1}])
    finally:
        trace_id_ctx.reset(token)

    assert body["error"]["details"] == [{"x": 1}]

    test_app = FastAPI()
    install_exception_handlers(test_app)

    @test_app.get("/http-string")
    def http_string():
        raise HTTPException(400, detail="plain failure")

    @test_app.get("/database")
    def database_failure():
        raise SQLAlchemyError("database unavailable")

    @test_app.get("/generic")
    def generic_failure():
        raise RuntimeError("unexpected")

    with TestClient(test_app, raise_server_exceptions=False) as client:
        string_response = client.get("/http-string")
        database_response = client.get("/database")
        generic_response = client.get("/generic")

    assert string_response.status_code == 400
    assert string_response.json()["error"]["code"] == "HTTP_ERROR"
    assert database_response.status_code == 503
    assert database_response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
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


def test_health_database_failure_and_metrics(monkeypatch):
    @contextmanager
    def broken_session():
        raise RuntimeError("database down")
        yield

    monkeypatch.setattr("app.main.SessionLocal", broken_session)
    health_response = health()
    metrics_response = metrics()

    assert health_response.status_code == 503
    assert b'"database":"DOWN"' in health_response.body
    assert metrics_response.status_code == 200
    assert b"account_http_requests_total" in metrics_response.body


def test_integrity_error_replay_branch(monkeypatch):
    command = TransactionCreate(**BASE)
    existing = SimpleNamespace(
        event_id=command.event_id,
        account_id=command.account_id,
        type=command.type.value,
        amount=command.amount,
        currency=command.currency,
        event_timestamp=command.event_timestamp.replace(tzinfo=None),
        applied_at=datetime.now(timezone.utc),
    )
    account = SimpleNamespace(balance=Decimal("10.00"), currency="USD")

    class FakeDB:
        def add(self, _value):
            pass

        def commit(self):
            raise IntegrityError("insert", {}, Exception("duplicate"))

        def rollback(self):
            pass

        def refresh(self, _value):
            pass

    service = AccountService(FakeDB())
    service.repo = SimpleNamespace(
        get_transaction=lambda _event_id: None,
        get_account=lambda _account_id: account if service.db_has_committed else None,
    )
    service.db_has_committed = False

    # Return no account before the attempted insert, then the persisted account after rollback.
    calls = {"account": 0}

    def get_account(_account_id):
        calls["account"] += 1
        return None if calls["account"] == 1 else account

    service.repo.get_account = get_account
    service.repo.get_transaction = lambda _event_id: existing if calls["account"] >= 1 else None
    service.audit = SimpleNamespace(record=lambda *args, **kwargs: None)

    result, created = service.apply(command.account_id, command)

    assert created is False
    assert result.idempotent_replay is True
    assert result.balance == Decimal("10.00")


def test_integrity_error_conflict_branch():
    command = TransactionCreate(**BASE)

    class FakeDB:
        def add(self, _value):
            pass

        def commit(self):
            raise IntegrityError("insert", {}, Exception("duplicate"))

        def rollback(self):
            pass

        def refresh(self, _value):
            pass

    service = AccountService(FakeDB())
    service.repo = SimpleNamespace(get_transaction=lambda _event_id: None, get_account=lambda _account_id: None)
    service.audit = SimpleNamespace(record=lambda *args, **kwargs: None)

    try:
        service.apply(command.account_id, command)
        raise AssertionError("expected conflict")
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "EVENT_ID_CONFLICT"
