.PHONY: up up-detached down logs test test-gateway test-account test-docker coverage functional-test clean

up:
	docker compose up --build

up-detached:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

test: test-account test-gateway

test-account:
	cd account-service && python -m pytest -q

test-gateway:
	cd event-gateway && python -m pytest -q

test-docker:
	docker compose run --rm account-service python -m pytest -q
	docker compose run --rm event-gateway python -m pytest -q

coverage:
	mkdir -p reports
	cd account-service && python -m pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-report=xml:../reports/account-coverage.xml | tee ../reports/account-coverage.txt
	cd event-gateway && python -m pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-report=xml:../reports/gateway-coverage.xml | tee ../reports/gateway-coverage.txt

functional-test:
	cd functional-tests && python -m pytest -v

clean:
	docker compose down -v --remove-orphans
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
	find . -name '.coverage' -delete
