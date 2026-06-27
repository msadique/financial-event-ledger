BASE={"eventId":"evt-1","accountId":"acct-1","type":"CREDIT","amount":"100.00","currency":"USD","eventTimestamp":"2026-05-15T14:02:11Z"}

def test_credit_debit_and_balance(client):
    assert client.post("/accounts/acct-1/transactions", json=BASE).status_code==201
    debit={**BASE,"eventId":"evt-2","type":"DEBIT","amount":"25.50","eventTimestamp":"2026-05-15T10:00:00Z"}
    assert client.post("/accounts/acct-1/transactions", json=debit).status_code==201
    data=client.get("/accounts/acct-1/balance").json()
    assert data["balance"]=="74.5000"

def test_duplicate_does_not_change_balance(client):
    assert client.post("/accounts/acct-1/transactions", json=BASE).status_code==201
    replay=client.post("/accounts/acct-1/transactions", json=BASE)
    assert replay.status_code==200 and replay.headers["Idempotent-Replay"]=="true"
    assert client.get("/accounts/acct-1/balance").json()["balance"]=="100.0000"

def test_conflicting_duplicate(client):
    client.post("/accounts/acct-1/transactions", json=BASE)
    assert client.post("/accounts/acct-1/transactions", json={**BASE,"amount":"101.00"}).status_code==409

def test_currency_mismatch(client):
    client.post("/accounts/acct-1/transactions", json=BASE)
    other={**BASE,"eventId":"evt-2","currency":"EUR"}
    assert client.post("/accounts/acct-1/transactions", json=other).status_code==409

def test_out_of_order_recent_transactions(client):
    late={**BASE,"eventId":"late","eventTimestamp":"2026-05-15T14:00:00Z"}
    early={**BASE,"eventId":"early","eventTimestamp":"2026-05-15T10:00:00Z"}
    client.post("/accounts/acct-1/transactions", json=late); client.post("/accounts/acct-1/transactions", json=early)
    txs=client.get("/accounts/acct-1").json()["recentTransactions"]
    assert [t["eventId"] for t in txs]==["late","early"]
