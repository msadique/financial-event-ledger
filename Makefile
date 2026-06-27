.PHONY: up down logs test test-gateway test-account clean

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test: test-account test-gateway

test-account:
	cd account-service && pytest -q

test-gateway:
	cd event-gateway && pytest -q

clean:
	docker compose down -v --remove-orphans
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
