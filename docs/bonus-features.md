# Bonus Feature Implementation

## 1. Gateway rate limiting

Implementation:

- `event-gateway/app/core/rate_limit.py`
- `event-gateway/app/main.py`

The Gateway uses a process-local sliding window keyed by client IP. Public API responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`. Rejected requests return HTTP 429, `Retry-After`, and the standard structured error contract.

Configuration:

```text
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
```

## 2. Pact contract tests

Implementation:

- `contract-tests/consumer/test_account_service_consumer_pact.py`
- `contract-tests/provider/test_account_service_provider_pact.py`
- `contract-tests/pacts/Event Gateway-Account Service.json`

Run:

```bash
make contract-test
```

The consumer test drives the real Gateway `AccountServiceClient` against a Pact mock. The provider test starts the real Account Service and verifies the generated Pact using `pact.Verifier`.

## 3. Durable async fallback queue

Implementation:

- `event-gateway/app/db/models.py` (`PendingDelivery`)
- `event-gateway/app/repositories/delivery_queue.py`
- `event-gateway/app/services/async_fallback.py`
- `event-gateway/app/services/event_service.py`
- `event-gateway/app/main.py`

When synchronous delivery fails, the Gateway returns HTTP 202 and stores a `QUEUED` event plus a durable queue record in SQLite. A background worker retries with exponential backoff and jitter until the Account Service recovers. Successful processing changes the event to `APPLIED` and removes the queue record.

Run the operational validation:

```bash
make test-resiliency
```
