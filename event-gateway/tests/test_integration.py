BASE_EVENT = {
    "eventId": "evt-integration-001",
    "accountId": "acct-integration-001",
    "type": "CREDIT",
    "amount": "100.00",
    "currency": "USD",
    "eventTimestamp": "2026-06-27T10:00:00Z",
    "metadata": {
        "source": "integration-test"
    },
}


def test_full_gateway_to_account_service_flow(client):
    create_response = client.post("/events", json=BASE_EVENT)

    assert create_response.status_code == 201
    created_event = create_response.json()

    assert created_event["eventId"] == BASE_EVENT["eventId"]
    assert created_event["accountId"] == BASE_EVENT["accountId"]
    assert created_event["processingStatus"] == "APPLIED"

    event_response = client.get(
        f"/events/{BASE_EVENT['eventId']}"
    )

    assert event_response.status_code == 200
    assert event_response.json()["eventId"] == BASE_EVENT["eventId"]

    balance_response = client.get(
        f"/accounts/{BASE_EVENT['accountId']}/balance"
    )

    assert balance_response.status_code == 200
    assert balance_response.json()["balance"] == "100.0000"

    replay_response = client.post("/events", json=BASE_EVENT)

    assert replay_response.status_code == 200

    final_balance_response = client.get(
        f"/accounts/{BASE_EVENT['accountId']}/balance"
    )

    assert final_balance_response.status_code == 200
    assert final_balance_response.json()["balance"] == "100.0000"