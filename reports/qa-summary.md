# QA Summary

## Automated results

| Suite | Result |
|---|---|
| Account Service unit/integration | 7 passed |
| Event Gateway unit/integration | 45 passed |
| Public-API functional | 5 passed |
| Account Service coverage | 91.13% |
| Event Gateway coverage | 100.00% |

## Covered quality areas

- Validation and standardized error responses
- Credit/debit balance calculations
- Duplicate replay and conflict behavior
- Out-of-order event handling
- Trace generation and propagation
- Durable audit records in both services
- Downstream retry/circuit behavior through unit tests
- Health and metrics endpoints
- Full Gateway-to-Account-Service integration

## Operational scenarios supplied

- `scripts/test-resiliency.sh`
- `scripts/test-persistence.sh`

These scripts are intentionally separate because they stop/restart Docker services and should run only against an isolated local Compose environment.
