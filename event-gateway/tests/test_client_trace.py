import httpx
import pytest

from app.clients.account_service import AccountServiceClient
from app.core.config import Settings
from app.core.tracing import trace_id_ctx


@pytest.mark.asyncio
async def test_client_propagates_trace_id():
    captured = {}

    async def handler(request: httpx.Request):
        captured["trace_id"] = request.headers.get("x-trace-id")
        return httpx.Response(201, json={"applied": True})

    settings = Settings(
        account_service_url="http://account-service",
        account_service_max_attempts=1,
        account_service_timeout_seconds=1,
    )
    client = AccountServiceClient(settings=settings, transport=httpx.MockTransport(handler))
    token = trace_id_ctx.set("trace-propagation-123")
    try:
        response = await client.apply_transaction(
            {
                "eventId": "evt-trace",
                "accountId": "acct-1",
                "type": "CREDIT",
                "amount": "1.00",
                "currency": "USD",
                "eventTimestamp": "2026-05-15T14:02:11+00:00",
            }
        )
    finally:
        trace_id_ctx.reset(token)

    assert response.status_code == 201
    assert captured["trace_id"] == "trace-propagation-123"
