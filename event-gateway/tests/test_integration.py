import time

import httpx


BASE_EVENT = {
    "eventId": "evt-integration-001",
    "accountId": "acct-integration-001",
    "type": "CREDIT",
    "amount": "100.00",
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z",
}


def wait_for_account_service() -> None:
    url = "http://account-service:8081/health"

    for _ in range(20):
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass

        time.sleep(0.25)

    raise RuntimeError("Account Service did not become healthy")


def test_full_gateway_to_account_service_flow(client):
    wait_for_account_service()

    response = client.post("/events", json=BASE_EVENT)

    assert response.status_code == 201
    assert response.json()["eventId"] == BASE_EVENT["eventId"]
    assert response.json()["processingStatus"] == "APPLIED"

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
    assert replay_response.headers["Idempotent-Replay"] == "true"

    final_balance_response = client.get(
        f"/accounts/{BASE_EVENT['accountId']}/balance"
    )

    assert final_balance_response.status_code == 200
    assert final_balance_response.json()["balance"] == "100.0000"