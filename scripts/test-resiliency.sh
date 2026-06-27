#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

BASE="${GATEWAY_URL:-http://localhost:8080}"
EVENT_ID="resilience-$(date +%s)-$$"
ACCOUNT_ID="acct-${EVENT_ID}"

cleanup() {
  echo
  echo "Cleanup: ensuring Account Service is running..."
  docker compose start account-service >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "1. Starting services..."
docker compose up -d --wait account-service event-gateway

echo
echo "2. Stopping Account Service..."
docker compose stop account-service

echo
echo "3. Submitting an event while Account Service is unavailable..."
response="$(
  curl -sS --max-time 20 \
    -w $'\n__STATUS__:%{http_code}\n__TIME__:%{time_total}' \
    -X POST "$BASE/events" \
    -H "Content-Type: application/json" \
    -H "X-Trace-ID: resilience-demo" \
    -d "{
      \"eventId\": \"$EVENT_ID\",
      \"accountId\": \"$ACCOUNT_ID\",
      \"type\": \"CREDIT\",
      \"amount\": \"25.00\",
      \"currency\": \"USD\",
      \"eventTimestamp\": \"2026-06-27T20:00:00Z\"
    }"
)"

echo "$response"
status="$(printf '%s\n' "$response" | sed -n 's/^__STATUS__://p')"
body="$(printf '%s\n' "$response" | sed '/^__STATUS__:/,$d')"

if [[ "$status" != "202" ]]; then
  echo "FAIL: expected HTTP 202 for a locally queued event, received $status"
  exit 1
fi

if [[ "$body" != *'"processingStatus":"QUEUED"'* ]]; then
  echo "FAIL: response did not report processingStatus QUEUED"
  exit 1
fi

echo "PASS: Gateway durably queued the event instead of losing it."

echo
echo "4. Restarting Account Service..."
docker compose start account-service

for _ in {1..30}; do
  if curl -fsS "http://localhost:8081/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo
echo "5. Waiting for the background worker to apply the queued event..."
for attempt in {1..60}; do
  event_json="$(curl -fsS "$BASE/events/$EVENT_ID")"
  status_value="$(printf '%s' "$event_json" | sed -n 's/.*"processingStatus":"\([A-Z]*\)".*/\1/p')"
  printf '\rAttempt %02d/60: processingStatus=%s' "$attempt" "${status_value:-UNKNOWN}"

  if [[ "$status_value" == "APPLIED" ]]; then
    echo
    balance="$(curl -fsS "$BASE/accounts/$ACCOUNT_ID/balance")"
    echo "Balance response: $balance"
    if [[ "$balance" != *'25.0000'* ]]; then
      echo "FAIL: queued event was applied but balance is incorrect"
      exit 1
    fi
    echo "PASS: queued event was automatically applied after recovery."
    echo "YES: async fallback resiliency validation passed."
    exit 0
  fi
  sleep 1
done

echo
echo "FAIL: queued event was not applied within 60 seconds"
docker compose logs --tail=100 event-gateway
exit 1
