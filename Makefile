.PHONY: help build up up-detached up-build down restart ps logs logs-gateway logs-account \
	test test-account test-gateway test-docker contract-test \
	coverage coverage-account coverage-gateway \
	functional-test test-resiliency test-persistence verify clean clean-all

help:
	@echo "Available commands:"
	@echo "  make build             Build Docker images"
	@echo "  make up                Build and start services in foreground"
	@echo "  make up-detached       Build and start services in background"
	@echo "  make up-build          Alias for up-detached"
	@echo "  make down              Stop and remove containers"
	@echo "  make restart           Restart services"
	@echo "  make ps                Show service status"
	@echo "  make logs              Follow all logs"
	@echo "  make logs-gateway      Follow Gateway logs"
	@echo "  make logs-account      Follow Account Service logs"
	@echo "  make test              Run service tests in Docker"
	@echo "  make contract-test     Generate and verify Pact contracts"
	@echo "  make coverage          Generate branch coverage reports"
	@echo "  make functional-test   Run tests against live APIs"
	@echo "  make test-resiliency   Validate async fallback and recovery"
	@echo "  make test-persistence  Validate SQLite persistence"
	@echo "  make verify            Run the complete validation workflow"
	@echo "  make clean             Remove containers and volumes"

build:
	docker compose build

up:
	docker compose up --build

up-detached:
	docker compose up --build -d --wait

up-build: up-detached

down:
	docker compose down

restart:
	docker compose down
	docker compose up --build -d --wait

ps:
	docker compose ps

logs:
	docker compose logs -f

logs-gateway:
	docker compose logs -f event-gateway

logs-account:
	docker compose logs -f account-service

# Run all unit and integration tests inside Docker.
test: test-account test-gateway

test-docker: test

test-account:
	docker compose run --build --rm account-service python -m pytest -q

test-gateway:
	docker compose run --build --rm event-gateway python -m pytest -q

# Generate a consumer Pact with the real Gateway client, then replay it against
# the real Account Service provider.
contract-test:
	rm -f contract-tests/pacts/*.json
	docker compose --profile test run --build --rm contract-consumer
	docker compose --profile test run --build --rm contract-provider

# Generate coverage reports inside Docker.
coverage: coverage-account coverage-gateway

coverage-account:
	docker compose run --build --rm account-service \
		sh -c "python -m pytest -q \
		--cov=app \
		--cov-branch \
		--cov-report=term-missing \
		--cov-report=xml:/reports/account-coverage.xml \
		| tee /reports/account-coverage.txt"

coverage-gateway:
	docker compose run --build --rm event-gateway \
		sh -c "python -m pytest -q \
		--cov=app \
		--cov-branch \
		--cov-report=term-missing \
		--cov-report=xml:/reports/gateway-coverage.xml \
		| tee /reports/gateway-coverage.txt"

# Run tests against the live Dockerized APIs.
functional-test:
	docker compose up --build -d --wait account-service event-gateway
	docker compose --profile test run --build --rm functional-tests

# Operational validation.
test-resiliency:
	bash scripts/test-resiliency.sh

test-persistence:
	bash scripts/test-persistence.sh

# Complete validation workflow.
verify:
	docker compose build
	$(MAKE) test
	$(MAKE) contract-test
	$(MAKE) coverage
	$(MAKE) functional-test
	$(MAKE) test-resiliency
	$(MAKE) test-persistence

clean:
	docker compose --profile test down -v --remove-orphans
	docker compose rm -f
	rm -f contract-tests/pacts/*.json

docker-clean:
	docker image prune -f

clean-all: clean docker-clean
