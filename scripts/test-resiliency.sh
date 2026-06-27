#!/usr/bin/env bash
set -euo pipefail
BASE=http://localhost:8080
ID="resilience-$(date +%s)"
docker compose stop account-service
trap 'docker compose start account-service >/dev/null' EXIT
status=$(curl -s -o /tmp/event-ledger-resilience.json -w '%{http_code}' -X POST "$BASE/events" -H 'Content-Type: application/json' -d "{\"eventId\":\"$ID\",\"accountId\":\"acct-$ID\",\"type\":\"CREDIT\",\"amount\":\"1.00\",\"currency\":\"USD\",\"eventTimestamp\":\"2026-06-27T17:00:00Z\"}")
test "$status" = "503"
curl -fsS "$BASE/events/$ID" >/dev/null
printf 'PASS: downstream failure returned 503 and Gateway-local event read remained available\n'
