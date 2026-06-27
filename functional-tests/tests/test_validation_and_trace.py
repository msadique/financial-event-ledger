def test_validation_error_contract(gateway, unique_id):
    response = gateway.post("/events", json={"eventId": unique_id, "amount": 0})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["traceId"]
    assert error["details"]


def test_trace_id_is_returned_and_propagated(gateway, account, unique_id):
    trace_id = "trace-" + unique_id
    event_id = "trace-event-" + unique_id
    body = {"eventId": event_id, "accountId": "trace-account-" + unique_id, "type": "CREDIT", "amount": "10", "currency": "USD", "eventTimestamp": "2026-06-27T15:00:00Z"}
    response = gateway.post("/events", json=body, headers={"X-Trace-ID": trace_id})
    assert response.status_code == 201
    assert response.headers["X-Trace-ID"] == trace_id
    gateway_audit = gateway.get(f"/audit/events/{event_id}").json()
    account_audit = account.get(f"/audit/events/{event_id}").json()
    assert any(item["traceId"] == trace_id for item in gateway_audit)
    assert any(item["traceId"] == trace_id for item in account_audit)
