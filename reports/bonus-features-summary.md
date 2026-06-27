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
- Event Gateway: 45 tests passed, 100.00% statement and branch coverage.
- Pact tests: 2 tests passed.

## Added edge-case coverage

The added `event-gateway/tests/test_bonus_coverage.py` suite covers rate-limit validation/reset, queue record updates, zero-attempt downstream configuration, async fallback backoff/retry/orphan/rejection paths, worker loop error recovery, application startup/shutdown lifecycle branches, middleware exception handling, direct 429 trace generation, and schema validation branches.
