BASE={"eventId":"evt-audit","accountId":"acct-audit","type":"CREDIT","amount":"100.00","currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z"}


def test_validation_error_has_standard_contract(client):
    response=client.post("/accounts/acct/transactions",json={"eventId":"bad","amount":0})
    assert response.status_code==422
    error=response.json()["error"]
    assert error["code"]=="VALIDATION_ERROR"
    assert error["traceId"]


def test_transaction_balance_and_replay_are_audited(client):
    assert client.post("/accounts/acct-audit/transactions",json=BASE,headers={"X-Trace-ID":"audit-trace"}).status_code==201
    assert client.post("/accounts/acct-audit/transactions",json=BASE,headers={"X-Trace-ID":"audit-trace"}).status_code==200
    conflict={**BASE,"amount":"200.00"}
    assert client.post("/accounts/acct-audit/transactions",json=conflict,headers={"X-Trace-ID":"audit-trace"}).status_code==409
    audits=client.get("/audit/events/evt-audit").json()
    actions=[item["action"] for item in audits]
    assert "ACCOUNT_CREATED" in actions
    assert "BALANCE_UPDATED" in actions
    assert "TRANSACTION_APPLIED" in actions
    assert "TRANSACTION_REPLAYED" in actions
    assert "TRANSACTION_CONFLICT_REJECTED" in actions
    assert all(item["traceId"]=="audit-trace" for item in audits)
