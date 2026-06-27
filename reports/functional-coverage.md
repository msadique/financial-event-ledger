# Functional Test Coverage

Functional tests exercise the running services through their HTTP APIs. The automated suite is located under `functional-tests/tests`.

| Requirement | Functional test | Coverage |
|---|---|---|
| Both services expose health checks | `test_both_services_are_healthy` | Automated |
| Both services expose metrics | `test_both_services_are_healthy` | Automated |
| Credit and debit update balance | `test_credit_debit_duplicate_conflict_and_audit` | Automated |
| Identical replay is idempotent | `test_credit_debit_duplicate_conflict_and_audit` | Automated |
| Conflicting replay returns 409 | `test_credit_debit_duplicate_conflict_and_audit` | Automated |
| Gateway audit trail is durable/queryable | `test_credit_debit_duplicate_conflict_and_audit` | Automated |
| Out-of-order events are listed chronologically | `test_out_of_order_listing` | Automated |
| Balance is independent of arrival order | `test_out_of_order_listing` | Automated |
| Validation returns standard error contract | `test_validation_error_contract` | Automated |
| Trace ID is returned and propagated | `test_trace_id_is_returned_and_propagated` | Automated |
| Account Service audit contains propagated trace | `test_trace_id_is_returned_and_propagated` | Automated |
| Account Service failure returns 503 | `scripts/test-resiliency.sh` | Docker scenario |
| Gateway-local reads survive downstream outage | `scripts/test-resiliency.sh` | Docker scenario |
| SQLite data survives container restart | `scripts/test-persistence.sh` | Docker scenario |

Run the automated functional suite with:

```bash
make functional-test
```

Run operational Docker scenarios with:

```bash
bash scripts/test-resiliency.sh
bash scripts/test-persistence.sh
```

## Verified automated run

The public-API functional suite was executed against two locally running service processes configured with separate file-based SQLite databases:

```text
5 passed in 0.44s
```

See `reports/functional-test-results.txt` for the captured output. Docker-only outage and container-restart scenarios are supplied as executable scripts; they require a Docker daemon and are not represented as executed in this environment.
