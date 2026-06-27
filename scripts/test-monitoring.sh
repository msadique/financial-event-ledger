#!/usr/bin/env bash

set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"
ACCOUNT_SERVICE_URL="${ACCOUNT_SERVICE_URL:-http://localhost:8081}"
COLLECTOR_METRICS_URL="${COLLECTOR_METRICS_URL:-http://localhost:8889/metrics}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"

MAX_ATTEMPTS="${MAX_ATTEMPTS:-30}"
WAIT_SECONDS="${WAIT_SECONDS:-2}"
REQUEST_COUNT="${REQUEST_COUNT:-30}"

REPORT_DIR="${REPORT_DIR:-reports}"

REQUEST_RESPONSE_FILE="${REPORT_DIR}/monitoring-request-response.json"
COLLECTOR_METRICS_FILE="${REPORT_DIR}/collector-span-metrics.txt"
PROMETHEUS_GATEWAY_FILE="${REPORT_DIR}/prometheus-gateway-metrics.json"
PROMETHEUS_ACCOUNT_FILE="${REPORT_DIR}/prometheus-account-metrics.json"
JAEGER_SERVICES_FILE="${REPORT_DIR}/jaeger-services.json"
JAEGER_CALLS_FILE="${REPORT_DIR}/jaeger-calls.json"
JAEGER_TRACE_FILE="${REPORT_DIR}/jaeger-distributed-trace.json"

mkdir -p "$REPORT_DIR"


print_section() {
    echo
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}


fail() {
    local message="$1"

    echo
    echo "FAIL: ${message}"
    echo
    echo "Container status:"
    docker compose ps || true
    echo
    echo "See service logs with:"
    echo "  docker compose logs otel-collector"
    echo "  docker compose logs prometheus"
    echo "  docker compose logs jaeger"
    exit 1
}


wait_for_url() {
    local name="$1"
    local url="$2"
    local output_file="${REPORT_DIR}/readiness-response.txt"
    local status_code=""

    echo "Waiting for ${name}: ${url}"

    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        rm -f "$output_file"

        status_code=$(
            curl -sS \
                -o "$output_file" \
                -w "%{http_code}" \
                "$url" 2>/dev/null || true
        )

        if [ "$status_code" = "200" ]; then
            echo "PASS: ${name} is available"
            rm -f "$output_file"
            return 0
        fi

        echo "Attempt ${attempt}/${MAX_ATTEMPTS}: ${name} not ready (HTTP ${status_code:-unavailable})"
        sleep "$WAIT_SECONDS"
    done

    fail "${name} did not become available: ${url}"
}


wait_for_collector_metrics() {
    echo "Waiting for Collector span-metrics endpoint: ${COLLECTOR_METRICS_URL}"

    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        rm -f "$COLLECTOR_METRICS_FILE"

        if curl -fsS \
            -o "$COLLECTOR_METRICS_FILE" \
            "$COLLECTOR_METRICS_URL" 2>/dev/null; then

            if grep -q "traces_span_metrics" "$COLLECTOR_METRICS_FILE"; then
                echo "PASS: Collector span-metrics endpoint is available"
                return 0
            fi
        fi

        echo "Attempt ${attempt}/${MAX_ATTEMPTS}: Collector metrics not ready"
        sleep "$WAIT_SECONDS"
    done

    fail "Collector span-metrics endpoint did not become available"
}


generate_traced_requests() {
    print_section "Generating ${REQUEST_COUNT} traced requests"

    local run_id
    local timestamp

    run_id="$(date +%s)"
    timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

    for index in $(seq 1 "$REQUEST_COUNT"); do
        local event_id
        local account_id
        local trace_id
        local status_code

        event_id="evt-monitoring-${run_id}-${index}"
        account_id="acct-monitoring-${run_id}"
        trace_id="monitoring-trace-${run_id}-${index}"

        rm -f "$REQUEST_RESPONSE_FILE"

        status_code=$(
            curl -sS \
                -o "$REQUEST_RESPONSE_FILE" \
                -w "%{http_code}" \
                -X POST "${GATEWAY_URL}/events" \
                -H "Content-Type: application/json" \
                -H "X-Trace-ID: ${trace_id}" \
                -d "{
                    \"eventId\": \"${event_id}\",
                    \"accountId\": \"${account_id}\",
                    \"type\": \"CREDIT\",
                    \"amount\": \"1.00\",
                    \"currency\": \"USD\",
                    \"eventTimestamp\": \"${timestamp}\",
                    \"metadata\": {
                        \"source\": \"monitoring-test\",
                        \"requestNumber\": ${index}
                    }
                }" || true
        )

        echo "Request ${index}/${REQUEST_COUNT}: HTTP ${status_code:-curl-error}"

        if [ "$status_code" != "201" ] &&
           [ "$status_code" != "200" ]; then
            echo
            echo "Response body:"
            cat "$REQUEST_RESPONSE_FILE" 2>/dev/null || true
            fail "Monitoring request ${index} returned HTTP ${status_code:-curl-error}"
        fi
    done

    rm -f "$REQUEST_RESPONSE_FILE"

    echo "PASS: Generated ${REQUEST_COUNT} traced Gateway-to-Account-Service requests"
}


validate_collector_metrics() {
    print_section "Validating Collector span metrics"

    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        rm -f "$COLLECTOR_METRICS_FILE"

        curl -fsS \
            -o "$COLLECTOR_METRICS_FILE" \
            "$COLLECTOR_METRICS_URL" 2>/dev/null || true

        if [ -s "$COLLECTOR_METRICS_FILE" ]; then
            local gateway_count
            local account_count

            gateway_count=$(
                awk '
                    /traces_span_metrics_calls_total/ &&
                    /service_name="event-gateway"/ {
                        total += $NF
                    }
                    END {
                        print total + 0
                    }
                ' "$COLLECTOR_METRICS_FILE"
            )

            account_count=$(
                awk '
                    /traces_span_metrics_calls_total/ &&
                    /service_name="account-service"/ {
                        total += $NF
                    }
                    END {
                        print total + 0
                    }
                ' "$COLLECTOR_METRICS_FILE"
            )

            if awk "BEGIN {exit !(${gateway_count} > 0 && ${account_count} > 0)}"; then
                echo "PASS: Collector generated non-zero span metrics"
                echo "  event-gateway calls: ${gateway_count}"
                echo "  account-service calls: ${account_count}"

                echo
                echo "Collector span-metric sample:"
                grep 'traces_span_metrics_calls_total' "$COLLECTOR_METRICS_FILE" |
                    grep -E 'service_name="event-gateway"|service_name="account-service"' |
                    head -20 || true

                return 0
            fi
        fi

        echo "Attempt ${attempt}/${MAX_ATTEMPTS}: Collector span metrics not ready"
        sleep "$WAIT_SECONDS"
    done

    fail "Collector did not generate non-zero span metrics for both services"
}


query_prometheus() {
    local query="$1"
    local output_file="$2"

    rm -f "$output_file"

    curl -G -fsS \
        -o "$output_file" \
        "${PROMETHEUS_URL}/api/v1/query" \
        --data-urlencode "query=${query}"
}


json_has_positive_prometheus_result() {
    local file="$1"

    python - "$file" <<'PY'
import json
import sys

path = sys.argv[1]

with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

if payload.get("status") != "success":
    raise SystemExit(1)

results = payload.get("data", {}).get("result", [])

if not results:
    raise SystemExit(1)

for result in results:
    value = result.get("value", [])
    if len(value) >= 2:
        try:
            if float(value[1]) > 0:
                raise SystemExit(0)
        except (TypeError, ValueError):
            pass

raise SystemExit(1)
PY
}


validate_prometheus() {
    print_section "Validating Prometheus"

    local gateway_query
    local account_query

    gateway_query='sum(traces_span_metrics_calls_total{service_name="event-gateway"})'
    account_query='sum(traces_span_metrics_calls_total{service_name="account-service"})'

    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        query_prometheus \
            "$gateway_query" \
            "$PROMETHEUS_GATEWAY_FILE" 2>/dev/null || true

        query_prometheus \
            "$account_query" \
            "$PROMETHEUS_ACCOUNT_FILE" 2>/dev/null || true

        if [ -s "$PROMETHEUS_GATEWAY_FILE" ] &&
           [ -s "$PROMETHEUS_ACCOUNT_FILE" ] &&
           json_has_positive_prometheus_result "$PROMETHEUS_GATEWAY_FILE" &&
           json_has_positive_prometheus_result "$PROMETHEUS_ACCOUNT_FILE"; then

            echo "PASS: Prometheus stored span metrics for event-gateway"
            echo "PASS: Prometheus stored span metrics for account-service"
            echo "PASS: Prometheus successfully scraped the Collector endpoint"
            return 0
        fi

        echo "Attempt ${attempt}/${MAX_ATTEMPTS}: Prometheus metrics not ready"
        sleep "$WAIT_SECONDS"
    done

    fail "Prometheus did not return non-zero metrics for both services"
}


validate_jaeger_services() {
    print_section "Validating Jaeger services"

    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        rm -f "$JAEGER_SERVICES_FILE"

        curl -fsS \
            -o "$JAEGER_SERVICES_FILE" \
            "${JAEGER_URL}/api/services" 2>/dev/null || true

        if [ -s "$JAEGER_SERVICES_FILE" ] &&
           python - "$JAEGER_SERVICES_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

services = payload.get("data", [])

required = {"event-gateway", "account-service"}

if not required.issubset(set(services)):
    raise SystemExit(1)
PY
        then
            echo "PASS: Jaeger lists event-gateway"
            echo "PASS: Jaeger lists account-service"
            return 0
        fi

        echo "Attempt ${attempt}/${MAX_ATTEMPTS}: Jaeger services not ready"
        sleep "$WAIT_SECONDS"
    done

    echo "Jaeger services response:"
    cat "$JAEGER_SERVICES_FILE" 2>/dev/null || true
    fail "Jaeger did not list both application services"
}


validate_jaeger_red_metrics() {
    print_section "Validating Jaeger RED metrics API"

    local metrics_url
    local status_code=""

    metrics_url="${JAEGER_URL}/api/metrics/calls?service=event-gateway&groupByOperation=true"

    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        rm -f "$JAEGER_CALLS_FILE"

        status_code=$(
            curl -sS \
                -o "$JAEGER_CALLS_FILE" \
                -w "%{http_code}" \
                "$metrics_url" 2>/dev/null || true
        )

        if [ "$status_code" = "200" ] &&
           [ -s "$JAEGER_CALLS_FILE" ] &&
           python - "$JAEGER_CALLS_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

if "data" not in payload:
    raise SystemExit(1)

data = payload["data"]

if data is None:
    raise SystemExit(1)

# Jaeger versions can return a list, object, or structured payload.
# HTTP 200 with a non-null data field confirms the metrics backend query worked.
raise SystemExit(0)
PY
        then
            echo "PASS: Jaeger RED metrics API returned HTTP 200"
            echo "PASS: Jaeger metrics backend returned valid JSON"
            echo "Saved response: ${JAEGER_CALLS_FILE}"
            return 0
        fi

        echo "Attempt ${attempt}/${MAX_ATTEMPTS}: Jaeger RED metrics not ready"
        sleep "$WAIT_SECONDS"
    done

    echo
    echo "Jaeger metrics HTTP status: ${status_code:-unavailable}"
    echo "Jaeger metrics response:"
    cat "$JAEGER_CALLS_FILE" 2>/dev/null || true

    fail "Jaeger RED metrics API validation failed"
}


validate_distributed_trace() {
    print_section "Validating distributed Gateway-to-Account-Service trace"

    local trace_url

    trace_url="${JAEGER_URL}/api/traces?service=event-gateway&operation=POST%20/events&limit=20"

    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        rm -f "$JAEGER_TRACE_FILE"

        curl -fsS \
            -o "$JAEGER_TRACE_FILE" \
            "$trace_url" 2>/dev/null || true

        if [ -s "$JAEGER_TRACE_FILE" ] &&
           python - "$JAEGER_TRACE_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

traces = payload.get("data", [])

for trace in traces:
    operations = {
        span.get("operationName")
        for span in trace.get("spans", [])
    }

    has_gateway = "POST /events" in operations
    has_account = (
        "POST /accounts/{account_id}/transactions"
        in operations
    )

    if has_gateway and has_account:
        raise SystemExit(0)

raise SystemExit(1)
PY
        then
            echo "PASS: Gateway POST /events span found"
            echo "PASS: Account Service transaction span found"
            echo "PASS: Trace context propagated across both services"
            echo "Saved response: ${JAEGER_TRACE_FILE}"
            return 0
        fi

        echo "Attempt ${attempt}/${MAX_ATTEMPTS}: Distributed trace not ready"
        sleep "$WAIT_SECONDS"
    done

    fail "Complete Gateway-to-Account-Service distributed trace was not found"
}


print_section "Starting application and observability services"

docker compose up \
    --build \
    --wait \
    account-service \
    event-gateway \
    otel-collector \
    prometheus \
    jaeger

docker compose ps

wait_for_url \
    "Event Gateway" \
    "${GATEWAY_URL}/health"

wait_for_url \
    "Account Service" \
    "${ACCOUNT_SERVICE_URL}/health"

wait_for_collector_metrics

wait_for_url \
    "Prometheus" \
    "${PROMETHEUS_URL}/-/ready"

wait_for_url \
    "Jaeger" \
    "${JAEGER_URL}/"

generate_traced_requests
validate_collector_metrics
validate_prometheus
validate_jaeger_services
validate_jaeger_red_metrics
validate_distributed_trace

print_section "Monitoring validation completed successfully"

echo "PASS: Event Gateway is healthy"
echo "PASS: Account Service is healthy"
echo "PASS: OpenTelemetry Collector receives application spans"
echo "PASS: Span-metrics connector generates RED metrics"
echo "PASS: Prometheus scrapes and stores span metrics"
echo "PASS: Jaeger stores traces"
echo "PASS: Jaeger queries its Prometheus metrics backend"
echo "PASS: Gateway-to-Account-Service trace propagation works"

echo
echo "Jaeger UI:     ${JAEGER_URL}"
echo "Prometheus UI: ${PROMETHEUS_URL}"
echo
echo "Generated reports:"
echo "  ${COLLECTOR_METRICS_FILE}"
echo "  ${PROMETHEUS_GATEWAY_FILE}"
echo "  ${PROMETHEUS_ACCOUNT_FILE}"
echo "  ${JAEGER_SERVICES_FILE}"
echo "  ${JAEGER_CALLS_FILE}"
echo "  ${JAEGER_TRACE_FILE}"