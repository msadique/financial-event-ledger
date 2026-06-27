# Enhancement Commit Commands

Apply these commits after copying the enhanced files into your repository.

## 1. Centralized error handling

```bash
git add event-gateway/app/core/errors.py account-service/app/core/errors.py \
  event-gateway/app/main.py account-service/app/main.py
git commit -m "feat(errors): standardize API error responses" \
  -m "Add validation, HTTP, database, and unexpected exception handlers with stable codes, retryability, and trace identifiers."
```

## 2. Durable auditing

```bash
git add event-gateway/app/db/models.py event-gateway/app/repositories/audit.py \
  event-gateway/app/schemas/audit.py event-gateway/app/api/routes_audit.py \
  event-gateway/app/services/event_service.py \
  account-service/app/db/models.py account-service/app/repositories/audit.py \
  account-service/app/schemas/audit.py account-service/app/api/routes_audit.py \
  account-service/app/services/account_service.py
git commit -m "feat(audit): add durable business audit trails" \
  -m "Persist event, transaction, replay, conflict, failure, account creation, and balance-change audit records with trace and business identifiers."
```

## 3. Logging enrichment

```bash
git add event-gateway/app/core/logging.py account-service/app/core/logging.py
git commit -m "feat(logging): enrich structured business logs" \
  -m "Include transaction type, processing status, audit action, and outcome fields while preserving trace-aware JSON logging."
```

## 4. QA and coverage

```bash
git add event-gateway/tests account-service/tests \
  event-gateway/pyproject.toml account-service/pyproject.toml \
  functional-tests reports
git commit -m "test: add audit, error, functional, and coverage verification" \
  -m "Add unit and public-API functional tests, branch coverage thresholds, XML reports, and requirement-to-test coverage evidence."
```

## 5. Docker test support

```bash
git add event-gateway/Dockerfile account-service/Dockerfile docker-compose.yml \
  Makefile scripts
git commit -m "build: enable Docker-based tests and operational scenarios" \
  -m "Install test extras in service images, expose local diagnostics, mount reports, and add resiliency and persistence scripts."
```

## 6. AI-SDLC documentation

```bash
git add README.md docs
git commit -m "docs: document AI-assisted engineering workflow" \
  -m "Describe Design, Development, and QA agent contributions, human review controls, diagrams, coverage, auditing, and professional commit practices."
```
