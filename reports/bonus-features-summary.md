# Bonus Features Verification

## Rate limiting

- Process-local sliding-window rate limiter on Gateway public APIs.
- Structured `429 RATE_LIMIT_EXCEEDED` response.
- `Retry-After` and `X-RateLimit-*` headers.
- Unit and middleware integration tests included in `event-gateway/tests/test_bonus_features.py`.

## Pact contract tests

- Consumer: Event Gateway.
- Provider: Account Service.
- Pact specification: V4.
- Covered interactions:
  - `POST /accounts/{accountId}/transactions`
  - `GET /accounts/{accountId}/balance`
- Consumer generation: 1 test passed.
- Provider verification: 1 test passed.

## Durable async fallback

- SQLite-backed `pending_deliveries` queue.
- Events return `202` with `processingStatus=QUEUED` during Account Service outages.
- Background worker retries with exponential backoff and jitter.
- Original trace ID is retained.
- Successful recovery changes the event to `APPLIED` and deletes the queue record.
- Unit/integration coverage is included in `event-gateway/tests/test_bonus_features.py`.

## Latest service results

- Account Service: 16 tests passed, 98.52% branch coverage.
- Event Gateway: 28 tests passed, 89.40% branch coverage.
- Pact tests: 2 tests passed.
