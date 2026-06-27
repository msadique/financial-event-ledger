from unittest.mock import AsyncMock
from app.clients.account_service import get_account_client
from app.db.session import get_db
from app.main import app
from app.repositories.audit import AuditRepository

BASE={"eventId":"evt-audit","accountId":"acct-audit","type":"CREDIT","amount":"100.00","currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z"}


def test_validation_error_has_standard_contract(client):
    response=client.post("/events",json={"eventId":"bad","amount":0})
    assert response.status_code==422
    body=response.json()["error"]
    assert body["code"]=="VALIDATION_ERROR"
    assert body["traceId"]
    assert isinstance(body["details"],list)


def test_success_replay_and_conflict_are_audited(client):
    downstream=AsyncMock()
    downstream.apply_transaction.return_value=type("R",(),{"status_code":201,"headers":{"content-type":"application/json"},"json":lambda self:{},"text":""})()
    app.dependency_overrides[get_account_client]=lambda:downstream
    try:
        assert client.post("/events",json=BASE,headers={"X-Trace-ID":"audit-trace"}).status_code==201
        assert client.post("/events",json=BASE,headers={"X-Trace-ID":"audit-trace"}).status_code==200
        conflict={**BASE,"amount":"200.00"}
        assert client.post("/events",json=conflict,headers={"X-Trace-ID":"audit-trace"}).status_code==409
        audits=client.get("/audit/events/evt-audit").json()
        actions=[item["action"] for item in audits]
        assert "EVENT_STORED" in actions
        assert "EVENT_APPLIED" in actions
        assert "EVENT_REPLAYED" in actions
        assert "EVENT_CONFLICT_REJECTED" in actions
        assert all(item["traceId"]=="audit-trace" for item in audits)
    finally:
        app.dependency_overrides.pop(get_account_client,None)
