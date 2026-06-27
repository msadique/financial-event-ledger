#!/usr/bin/env bash
set -euo pipefail
BASE=http://localhost:8080
ID="persist-$(date +%s)"
curl -fsS -X POST "$BASE/events" -H 'Content-Type: application/json' -d "{\"eventId\":\"$ID\",\"accountId\":\"acct-$ID\",\"type\":\"CREDIT\",\"amount\":\"75.00\",\"currency\":\"USD\",\"eventTimestamp\":\"2026-06-27T18:00:00Z\"}" >/dev/null
docker compose down
docker compose up -d
for _ in {1..30}; do curl -fsS "$BASE/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "$BASE/events/$ID" >/dev/null
balance=$(curl -fsS "$BASE/accounts/acct-$ID/balance")
echo "$balance" | grep -q '75.0000'
printf 'PASS: event and balance survived container recreation\n'
