from __future__ import annotations

import os
from pathlib import Path

import pytest
from pact import Pact, match

from app.clients.account_service import AccountServiceClient
from app.core.config import Settings
from app.core.tracing import trace_context

PACT_DIR = Path(os.getenv("PACT_DIR", "/contracts/pacts"))
TRACE_ID = "contract-trace-001"
ACCOUNT_ID = "acct-contract-001"
EVENT_ID = "evt-contract-001"

TRANSACTION = {
    "eventId": EVENT_ID,
    "accountId": ACCOUNT_ID,
    "type": "CREDIT",
    "amount": "25.00",
    "currency": "USD",
    "eventTimestamp": "2026-06-27T10:00:00Z",
}


@pytest.mark.asyncio
async def test_gateway_account_service_contract():
    pact = Pact("Event Gateway", "Account Service").with_specification("V4")

    (
        pact.upon_receiving("apply a new credit transaction")
        .given("no transaction exists", eventId=EVENT_ID, accountId=ACCOUNT_ID)
        .with_request("POST", f"/accounts/{ACCOUNT_ID}/transactions")
        .with_header("X-Trace-ID", TRACE_ID, part="Request")
        .with_body(TRANSACTION, content_type="application/json", part="Request")
        .will_respond_with(201)
        .with_body(
            {
                "eventId": match.str(EVENT_ID),
                "accountId": match.str(ACCOUNT_ID),
                "applied": match.bool(True),
                "idempotentReplay": match.bool(False),
                "balance": match.str("25.0000"),
                "currency": match.str("USD"),
                "appliedAt": match.regex(
                    "2026-06-27T10:00:01.000000",
                    regex=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$",
                ),
            },
            content_type="application/json",
            part="Response",
        )
    )

    (
        pact.upon_receiving("get an existing account balance")
        .given("account exists", accountId=ACCOUNT_ID, balance="42.0000", currency="USD")
        .with_request("GET", f"/accounts/{ACCOUNT_ID}/balance")
        .with_header("X-Trace-ID", TRACE_ID, part="Request")
        .will_respond_with(200)
        .with_body(
            {
                "accountId": match.str(ACCOUNT_ID),
                "currency": match.str("USD"),
                "balance": match.str("42.0000"),
                "updatedAt": match.regex(
                    "2026-06-27T10:00:01.000000",
                    regex=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$",
                ),
            },
            content_type="application/json",
            part="Response",
        )
    )

    with pact.serve() as server, trace_context(TRACE_ID):
        client = AccountServiceClient(
            Settings(
                account_service_url=str(server.url),
                account_service_timeout_seconds=2,
                account_service_max_attempts=1,
                circuit_breaker_failure_threshold=5,
            )
        )

        transaction_response = await client.apply_transaction(TRANSACTION)
        balance_response = await client.get_balance(ACCOUNT_ID)

        assert transaction_response.status_code == 201
        assert transaction_response.json()["balance"] == "25.0000"
        assert balance_response.status_code == 200
        assert balance_response.json()["balance"] == "42.0000"

    PACT_DIR.mkdir(parents=True, exist_ok=True)
    pact.write_file(PACT_DIR, overwrite=True)
