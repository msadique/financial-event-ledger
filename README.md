# Event Ledger

A two-service financial event ledger that demonstrates idempotent processing, out-of-order event handling, synchronous REST communication, distributed trace propagation, structured logging, resiliency, health checks, metrics, Docker Compose, and automated tests.

## Architecture

```text
Client -> Event Gateway (SQLite) -> Account Service (SQLite)
             |                           |
             +-- public event APIs       +-- balances and transaction ledger
```

The services do not share a database or in-process state. The Gateway owns public event records. The Account Service owns balances and the applied transaction ledger.

## Key decisions

- **Decimal money:** Python `Decimal` and SQL `NUMERIC(19, 4)` are used instead of floating point.
- **Idempotency in both services:** `eventId` is a database primary key in each service. A matching replay returns the original result; a conflicting replay returns `409`.
- **Out-of-order tolerance:** balances are additive, while event and transaction queries sort by `eventTimestamp`.
- **Failure semantics:** the Gateway stores a new event as `PENDING`, calls the Account Service, then sets it to `APPLIED` or `FAILED`.
- **Resiliency:** bounded timeout, exponential backoff with jitter, and a process-local circuit breaker protect the downstream call.
- **Traceability:** `X-Trace-ID` is accepted/generated at the Gateway, propagated to the Account Service, logged by both, and returned in responses.

## Start with Docker

```bash
docker compose up --build
```

Gateway: `http://localhost:8080`  
Gateway OpenAPI: `http://localhost:8080/docs`

The Account Service is internal to the Compose network. For manual development, run it on port `8081`.

## Manual setup

Use Python 3.11+.

Terminal 1:

```bash
cd account-service
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .[test]
uvicorn app.main:app --host 0.0.0.0 --port 8081
```

Terminal 2:

```bash
cd event-gateway
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
export ACCOUNT_SERVICE_URL=http://localhost:8081
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## API examples

Submit an event:

```bash
curl -i -X POST http://localhost:8080/events \
  -H 'Content-Type: application/json' \
  -H 'X-Trace-ID: demo-trace-001' \
  -d '{
    "eventId": "evt-001",
    "accountId": "acct-123",
    "type": "CREDIT",
    "amount": "150.00",
    "currency": "USD",
    "eventTimestamp": "2026-05-15T14:02:11Z",
    "metadata": {"source": "mainframe-batch", "batchId": "B-9042"}
  }'
```

Query events and balance:

```bash
curl http://localhost:8080/events/evt-001
curl 'http://localhost:8080/events?account=acct-123'
curl http://localhost:8080/accounts/acct-123/balance
```

Health and metrics:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/metrics
```

## Run tests

From the repository root:

```bash
make test
```

Or run each suite directly:

```bash
cd account-service && pytest -q
cd event-gateway && pytest -q
```

The tests cover validation, balance calculations, duplicate and conflicting events, chronological ordering, downstream failure, retry/circuit behavior, trace propagation, and a full Gateway-to-Account-Service flow using an in-process ASGI transport.

## API status behavior

| Scenario | Status |
|---|---:|
| New event applied | 201 |
| Identical duplicate | 200 |
| Same ID with conflicting payload | 409 |
| Invalid payload | 422 |
| Unknown event/account | 404 |
| Account Service unavailable | 503 |

## Consistency and trade-offs

There is no distributed transaction across the two SQLite databases. If the downstream request times out after being applied, the Gateway may mark its record `FAILED` even though the Account Service committed it. Account-Service idempotency makes a later safe replay possible. A production system would add an outbox, queue, or reconciliation worker.

The circuit breaker is process-local, which is suitable for this exercise. In a horizontally scaled production deployment, each instance would maintain independent breaker state or use infrastructure-level resiliency.

## Repository documents

- `docs/requirements.docx`
- `docs/design.docx`
