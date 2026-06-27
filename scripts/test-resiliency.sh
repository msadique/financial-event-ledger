#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:8080"

cleanup() {
  docker compose start account-service >/dev/null 2>&1 || true
}

trap cleanup EXIT

docker compose stop account-service

status=$(curl -s -o response.json -w "%{http_code}" \
  -X POST "$BASE/events" \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "resilience-test-001",
    "accountId": "acct-resilience-001",
    "type": "CREDIT",
    "amount": "25.00",
    "currency": "USD",
    "eventTimestamp": "2026-06-27T20:00:00Z"
  }')

if [ "$status" != "503" ]; then
  echo "FAIL: expected HTTP 503, received $status"
  cat response.json
  exit 1
fi

curl -fsS "$BASE/health" >/dev/null

docker compose start account-service

printf 'PASS: Gateway returned 503 and remained available while Account Service was down\n'