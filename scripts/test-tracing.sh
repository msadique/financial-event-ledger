#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
RUN_ID="$(date +%s)-$$"
EVENT_ID="otel-${RUN_ID}"
ACCOUNT_ID="otel-account-${RUN_ID}"
CORRELATION_ID="otel-demo-${RUN_ID}"

echo "Starting application, OpenTelemetry Collector, and Jaeger..."
docker compose up --build -d --wait

echo
echo "Submitting a traced event..."
response="$(
  curl -sS -i -X POST "${GATEWAY_URL}/events" \
    -H "Content-Type: application/json" \
    -H "X-Trace-ID: ${CORRELATION_ID}" \
    -d "{
      \"eventId\": \"${EVENT_ID}\",
      \"accountId\": \"${ACCOUNT_ID}\",
      \"type\": \"CREDIT\",
      \"amount\": \"15.00\",
      \"currency\": \"USD\",
      \"eventTimestamp\": \"2026-06-27T10:00:00Z\"
    }"
)"
printf '%s\n' "$response"

normalized="$(printf '%s\n' "$response" | tr -d '\r')"
status="$(printf '%s\n' "$normalized" | awk 'NR==1 {print $2}')"
otel_trace_id="$(printf '%s\n' "$normalized" | awk -F': ' 'tolower($1)=="x-opentelemetry-trace-id" {print $2; exit}')"

if [[ "$status" != "201" ]]; then
  echo "FAIL: expected HTTP 201, received ${status:-unknown}."
  exit 1
fi
if [[ ! "$otel_trace_id" =~ ^[0-9a-f]{32}$ ]]; then
  echo "FAIL: X-OpenTelemetry-Trace-ID header was not returned."
  exit 1
fi

echo
echo "OpenTelemetry trace ID: $otel_trace_id"
echo "Waiting for the Collector to export the trace to Jaeger..."

for attempt in $(seq 1 30); do
  trace_json="$(curl -fsS "${JAEGER_URL}/api/traces/${otel_trace_id}" 2>/dev/null || true)"
  if [[ -n "$trace_json" ]] && printf '%s' "$trace_json" | python -c '
import json, sys
try:
    payload = json.load(sys.stdin)
    traces = payload.get("data", [])
    services = {
        process.get("serviceName")
        for trace in traces
        for process in trace.get("processes", {}).values()
    }
    ok = {"event-gateway", "account-service"}.issubset(services)
except Exception:
    ok = False
raise SystemExit(0 if ok else 1)
'; then
    echo "PASS: Jaeger contains one distributed trace spanning event-gateway and account-service."
    echo "Open Jaeger UI: ${JAEGER_URL}/trace/${otel_trace_id}"
    exit 0
  fi
  echo "Attempt ${attempt}/30: trace not available yet"
  sleep 1
done

echo "FAIL: trace was not found in Jaeger within 30 seconds."
echo "Collector logs:"
docker compose logs --tail=50 otel-collector || true
echo "Jaeger logs:"
docker compose logs --tail=50 jaeger || true
exit 1
