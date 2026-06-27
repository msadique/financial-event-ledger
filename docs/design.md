# Event Ledger Design Summary

## Architecture

```text
Client
  |
  v
Event Gateway :8080 ----REST + X-Trace-ID----> Account Service :8081
  |                                                  |
  v                                                  v
Gateway SQLite                                  Account SQLite
(events, audit_records)                         (accounts, transactions, audit_records)
```

The Gateway owns event intake and public event queries. The Account Service owns account state and transaction history. The services do not share a database.

## Request flow

1. Gateway accepts or generates `X-Trace-ID`.
2. Pydantic validates the financial event.
3. Gateway detects replay or conflict by `eventId`.
4. A new event is stored as `PENDING` and audited.
5. Gateway calls Account Service using timeout, bounded retry, backoff, jitter, and a circuit breaker.
6. Account Service independently deduplicates the transaction and atomically updates the account and audit trail.
7. Gateway marks the event `APPLIED` or `FAILED` and writes a durable audit record.

## Error contract

```json
{
  "error": {
    "code": "ACCOUNT_SERVICE_UNAVAILABLE",
    "message": "Account processing is temporarily unavailable",
    "traceId": "...",
    "retryable": true
  }
}
```

## Auditing

Both services maintain a local `audit_records` table. Audit records include action, outcome, trace ID, event ID, account ID, non-sensitive details, and timestamp. Account transaction and balance audit entries are committed in the same local transaction as the ledger update.

## Persistence choice

File-based SQLite was selected instead of an in-memory database so data survives process and container restarts while retaining the assignment's embedded-database simplicity. Docker named volumes persist each database independently. `docker compose down -v` intentionally resets them. PostgreSQL would be preferred for high-concurrency production use.

## Known consistency trade-off

There is no distributed transaction across the Gateway and Account Service databases. A timeout can leave the Gateway at `FAILED` after the Account Service committed. Independent downstream idempotency permits safe replay; a production design would add an outbox, queue, or reconciliation worker.
