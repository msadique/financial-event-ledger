.PHONY: build up up-detached down restart ps logs \
	test test-account test-gateway test-docker \
	coverage coverage-account coverage-gateway \
	functional-test verify clean

build:
	docker compose build

up:
	docker compose up --build

up-detached:
	docker compose up --build -d

down:
	docker compose down

restart:
	docker compose down
	docker compose up --build -d

ps:
	docker compose ps

logs:
	docker compose logs -f

# Run all unit and integration tests inside Docker.
test: test-account test-gateway

test-docker: test

test-account:
	docker compose run --build --rm account-service \
		python -m pytest -q

test-gateway:
	docker compose run --build --rm event-gateway \
		python -m pytest -q

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
	docker compose up --build -d account-service event-gateway
	docker compose run --build --rm functional-tests \
		python -m pytest -v
	docker compose down

# Complete validation workflow.
verify:
	docker compose build
	$(MAKE) test
	$(MAKE) coverage
	$(MAKE) functional-test

clean:
	docker compose down -v --remove-orphans
	docker compose rm -f
	docker image prune -f