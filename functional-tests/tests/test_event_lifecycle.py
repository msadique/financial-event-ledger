def payload(event_id, account_id, kind="CREDIT", amount="100.00", timestamp="2026-06-27T10:00:00Z"):
    return {"eventId": event_id, "accountId": account_id, "type": kind, "amount": amount, "currency": "USD", "eventTimestamp": timestamp}


def test_credit_debit_duplicate_conflict_and_audit(gateway, unique_id):
    account_id = f"acct-{unique_id}"
    credit = payload(f"credit-{unique_id}", account_id, amount="150.00")
    debit = payload(f"debit-{unique_id}", account_id, "DEBIT", "40.00", "2026-06-27T11:00:00Z")
    assert gateway.post("/events", json=credit).status_code == 201
    assert gateway.post("/events", json=debit).status_code == 201
    assert gateway.get(f"/accounts/{account_id}/balance").json()["balance"] == "110.0000"
    replay = gateway.post("/events", json=credit)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    conflict = dict(credit, amount="999.00")
    assert gateway.post("/events", json=conflict).status_code == 409
    actions = [a["action"] for a in gateway.get(f"/audit/events/{credit['eventId']}").json()]
    assert "EVENT_APPLIED" in actions
    assert "EVENT_REPLAYED" in actions
    assert "EVENT_CONFLICT_REJECTED" in actions


def test_out_of_order_listing(gateway, unique_id):
    account_id = f"order-{unique_id}"
    events = [
        payload(f"e3-{unique_id}", account_id, "DEBIT", "30", "2026-06-27T14:00:00Z"),
        payload(f"e1-{unique_id}", account_id, "CREDIT", "100", "2026-06-27T10:00:00Z"),
        payload(f"e2-{unique_id}", account_id, "CREDIT", "20", "2026-06-27T12:00:00Z"),
    ]
    for event in events:
        assert gateway.post("/events", json=event).status_code == 201
    listed = gateway.get("/events", params={"account": account_id}).json()["items"]
    assert [item["eventId"] for item in listed] == [f"e1-{unique_id}", f"e2-{unique_id}", f"e3-{unique_id}"]
    assert gateway.get(f"/accounts/{account_id}/balance").json()["balance"] == "90.0000"
