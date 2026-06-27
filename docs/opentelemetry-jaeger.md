# OpenTelemetry Collector, Prometheus, and Jaeger

## Data flow

```text
Client
  |
  v
Event Gateway -- W3C traceparent --> Account Service
      |                                  |
      +----------- OTLP/HTTP ------------+
                     |
                     v
          OpenTelemetry Collector
             |                 |
        OTLP/gRPC         spanmetrics
             |                 |
             v                 v
           Jaeger <-------- Prometheus
             |
             v
      Search and Monitor UI
```

The existing `X-Trace-ID` remains the application correlation identifier. OpenTelemetry creates a standards-based distributed trace ID and the Gateway returns it in the `X-OpenTelemetry-Trace-ID` response header.

The Collector also converts spans into RED metrics:

- Request rate
- Error rate
- Duration/latency histograms

Prometheus scrapes those metrics, and Jaeger queries Prometheus to populate the **Monitor** tab.

## Start

```bash
make up-build
```

Endpoints:

- Gateway: `http://localhost:8080`
- OpenTelemetry Collector OTLP/gRPC: `localhost:4317`
- OpenTelemetry Collector OTLP/HTTP: `localhost:4318`
- Collector health extension: `http://localhost:13133`
- Collector span-metrics endpoint: `http://localhost:8889/metrics`
- Prometheus UI: `http://localhost:9090`
- Jaeger UI: `http://localhost:16686`
- Jaeger Monitor: `http://localhost:16686/monitor`
- Jaeger image: `jaegertracing/jaeger:2.19.0`

## Distributed trace validation

```bash
make test-tracing
```

The script:

1. Starts the application, Collector, Prometheus, and Jaeger.
2. Submits a financial event through the Gateway.
3. Reads `X-OpenTelemetry-Trace-ID` from the response.
4. Polls the Jaeger query API.
5. Verifies that the trace contains both `event-gateway` and `account-service`.

## Jaeger Monitor validation

```bash
make test-monitoring
```

The script:

1. Generates 60 traced Gateway requests, spaced one second apart.
2. Confirms the Collector generated `calls_total` and duration metrics for both services.
3. Confirms Prometheus stored the span metrics.
4. Waits for Collector and Prometheus flush cycles and confirms Jaeger's RED-metrics API returns non-empty metric points.

After it passes, open `http://localhost:16686/monitor`, select `event-gateway`, select `Server`, and use the **Last Hour** time range.

## Manual trace validation

```bash
RUN_ID="$(date +%s)"

curl -i -X POST http://localhost:8080/events \
  -H 'Content-Type: application/json' \
  -H "X-Trace-ID: manual-${RUN_ID}" \
  -d "{
    \"eventId\": \"manual-otel-${RUN_ID}\",
    \"accountId\": \"manual-account-${RUN_ID}\",
    \"type\": \"CREDIT\",
    \"amount\": \"25.00\",
    \"currency\": \"USD\",
    \"eventTimestamp\": \"2026-06-27T10:00:00Z\"
  }"
```

Copy the `X-OpenTelemetry-Trace-ID` response header and open:

```text
http://localhost:16686/trace/<trace-id>
```

## Manual Monitor validation

Generate enough traffic to create a useful time series:

```bash
for i in $(seq 1 60); do
  RUN_ID="$(date +%s)-$i"
  curl -s -X POST http://localhost:8080/events \
    -o "monitor-response-${i}.json" \
    -H 'Content-Type: application/json' \
    -d "{
      \"eventId\": \"monitor-${RUN_ID}\",
      \"accountId\": \"monitor-account-${RUN_ID}\",
      \"type\": \"CREDIT\",
      \"amount\": \"10.00\",
      \"currency\": \"USD\",
      \"eventTimestamp\": \"2026-06-27T10:00:00Z\"
    }"
  sleep 1
done
```

Verify Collector output:

```bash
curl -s http://localhost:8889/metrics \
  | grep -E 'calls_total|duration_.*_(count|bucket)' \
  | head -30
```

Verify Prometheus:

```bash
curl -s -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query={__name__=~".*calls_total"}' \
  | python -m json.tool
```

Verify Jaeger metrics API:

```bash
curl -s -G http://localhost:16686/api/metrics/calls \
  --data-urlencode 'service=event-gateway' \
  --data-urlencode 'groupByOperation=true' \
  --data-urlencode 'spanKind=server' \
  | python -m json.tool
```

## Diagnostics

```bash
docker compose ps
docker compose logs -f otel-collector
docker compose logs -f prometheus
docker compose logs -f jaeger
docker compose logs -f event-gateway account-service
```

Check Prometheus targets at `http://localhost:9090/targets`. The `otel-spanmetrics` target should be **UP**.

## Configuration files

- `otel-collector-config.yaml` receives traces, exports traces to Jaeger, and produces span metrics.
- `prometheus.yml` scrapes Collector span metrics and Jaeger internal metrics.
- `jaeger-config.yaml` configures in-memory trace storage and Prometheus as Jaeger's metrics backend.

Application settings:

```text
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORT_TIMEOUT_SECONDS=5
OTEL_SERVICE_VERSION=0.4.0
OTEL_ENVIRONMENT=docker
OTEL_EXCLUDED_URLS=health,metrics
```

For local execution outside Docker, use `http://localhost:4318` as the OTLP endpoint.
