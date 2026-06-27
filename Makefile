.DEFAULT_GOAL := help

COMPOSE ?= docker compose

.PHONY: help \
	build up up-detached up-build down restart ps \
	logs logs-gateway logs-account logs-collector logs-jaeger logs-prometheus \
	test test-account test-gateway test-docker \
	contract-test \
	coverage coverage-account coverage-gateway \
	functional-test \
	test-resiliency test-persistence test-tracing test-monitoring \
	verify \
	clean docker-clean clean-all


# ------------------------------------------------------------
# Help
# ------------------------------------------------------------

help:
	@echo "Available commands:"
	@echo ""
	@echo "Docker:"
	@echo "  make build             Build Docker images"
	@echo "  make up                Build and start services in foreground"
	@echo "  make up-detached       Build and start services in background"
	@echo "  make up-build          Alias for make up-detached"
	@echo "  make down              Stop and remove containers"
	@echo "  make restart           Restart the complete stack"
	@echo "  make ps                Show container status"
	@echo ""
	@echo "Logs:"
	@echo "  make logs              Follow logs from all services"
	@echo "  make logs-gateway      Follow Event Gateway logs"
	@echo "  make logs-account      Follow Account Service logs"
	@echo "  make logs-collector    Follow OpenTelemetry Collector logs"
	@echo "  make logs-jaeger       Follow Jaeger logs"
	@echo "  make logs-prometheus   Follow Prometheus logs"
	@echo ""
	@echo "Tests:"
	@echo "  make test              Run all service tests in Docker"
	@echo "  make test-account      Run Account Service tests"
	@echo "  make test-gateway      Run Event Gateway tests"
	@echo "  make contract-test     Generate and verify Pact contracts"
	@echo "  make coverage          Generate branch coverage reports"
	@echo "  make functional-test   Run tests against live APIs"
	@echo ""
	@echo "Operational validation:"
	@echo "  make test-resiliency   Validate fallback queue and recovery"
	@echo "  make test-persistence  Validate SQLite persistence"
	@echo "  make test-tracing      Validate Collector and Jaeger traces"
	@echo "  make test-monitoring   Validate spanmetrics, Prometheus, and Jaeger Monitor"
	@echo "  make verify            Run the complete validation workflow"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean             Remove containers, volumes, and test artifacts"
	@echo "  make docker-clean      Remove unused Docker images"
	@echo "  make clean-all         Run clean and docker-clean"


# ------------------------------------------------------------
# Docker lifecycle
# ------------------------------------------------------------

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up --build

up-detached:
	$(COMPOSE) up --build -d --wait

up-build: up-detached

down:
	$(COMPOSE) --profile test down --remove-orphans

restart:
	$(COMPOSE) --profile test down --remove-orphans
	$(COMPOSE) up --build -d --wait

ps:
	$(COMPOSE) ps


# ------------------------------------------------------------
# Logs
# ------------------------------------------------------------

logs:
	$(COMPOSE) logs -f

logs-gateway:
	$(COMPOSE) logs -f event-gateway

logs-account:
	$(COMPOSE) logs -f account-service

logs-collector:
	$(COMPOSE) logs -f otel-collector

logs-jaeger:
	$(COMPOSE) logs -f jaeger

logs-prometheus:
	$(COMPOSE) logs -f prometheus


# ------------------------------------------------------------
# Unit and integration tests
#
# -T disables pseudo-TTY allocation. This keeps pytest output visible and
# avoids terminal issues when running from Cygwin, Git Bash, or CI.
# ------------------------------------------------------------

test: test-account test-gateway

test-docker: test

test-account:
	$(COMPOSE) run --build --rm -T \
		-e OTEL_ENABLED=false \
		account-service \
		python -m pytest -q -ra

test-gateway:
	$(COMPOSE) run --build --rm -T \
		-e OTEL_ENABLED=false \
		event-gateway \
		python -m pytest -q -ra


# ------------------------------------------------------------
# Pact contract tests
# ------------------------------------------------------------

contract-test:
	rm -f contract-tests/pacts/*.json
	$(COMPOSE) --profile test run --build --rm -T \
		contract-consumer
	$(COMPOSE) --profile test run --build --rm -T \
		contract-provider


# ------------------------------------------------------------
# Branch-aware coverage reports
#
# The commands preserve the pytest exit code while also writing readable
# text reports under reports/.
# ------------------------------------------------------------

coverage: coverage-account coverage-gateway

coverage-account:
	$(COMPOSE) run --build --rm -T \
		-e OTEL_ENABLED=false \
		account-service \
		sh -c 'python -m pytest -q -ra \
			--cov=app \
			--cov-branch \
			--cov-report=term-missing \
			--cov-report=xml:/reports/account-coverage.xml \
			> /reports/account-coverage.txt 2>&1; \
			status=$$?; \
			cat /reports/account-coverage.txt; \
			exit $$status'

coverage-gateway:
	$(COMPOSE) run --build --rm -T \
		-e OTEL_ENABLED=false \
		event-gateway \
		sh -c 'python -m pytest -q -ra \
			--cov=app \
			--cov-branch \
			--cov-report=term-missing \
			--cov-report=xml:/reports/gateway-coverage.xml \
			> /reports/gateway-coverage.txt 2>&1; \
			status=$$?; \
			cat /reports/gateway-coverage.txt; \
			exit $$status'


# ------------------------------------------------------------
# Live API functional tests
# ------------------------------------------------------------

functional-test:
	$(COMPOSE) up --build -d --wait \
		account-service \
		event-gateway
	$(COMPOSE) --profile test run --build --rm -T \
		functional-tests


# ------------------------------------------------------------
# Operational validation
# ------------------------------------------------------------

test-resiliency:
	bash scripts/test-resiliency.sh

test-persistence:
	bash scripts/test-persistence.sh

test-tracing:
	bash scripts/test-tracing.sh

test-monitoring:
	bash scripts/test-monitoring.sh


# ------------------------------------------------------------
# Complete validation workflow
# ------------------------------------------------------------

verify:
	$(COMPOSE) build
	$(MAKE) test
	$(MAKE) contract-test
	$(MAKE) coverage
	$(MAKE) functional-test
	$(MAKE) test-resiliency
	$(MAKE) test-persistence
	$(MAKE) test-tracing
	$(MAKE) test-monitoring


# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------

clean:
	$(COMPOSE) --profile test down -v --remove-orphans
	$(COMPOSE) rm -f
	rm -f contract-tests/pacts/*.json

docker-clean:
	docker image prune -f

clean-all: clean docker-clean
