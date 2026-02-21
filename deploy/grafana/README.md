# Grafana Dashboards for Cortex

Pre-built dashboards for monitoring a Cortex CaaS server with Prometheus metrics enabled.

## Dashboards

| Dashboard | File | Description |
|-----------|------|-------------|
| Overview | `cortex-overview.json` | HTTP request rates, latency percentiles, errors, in-flight requests, active grants |
| Graph & Cache | `cortex-graph.json` | Node/edge counts, cache hit ratio, SSE subscribers, audit entries |
| Webhooks | `cortex-webhooks.json` | Delivery rates, dead-letter queue depth, circuit breaker state |

## Quick Start

### Option 1: Import manually

1. Open Grafana (default: http://localhost:3000)
2. Go to Dashboards > Import
3. Upload any of the JSON files from this directory

### Option 2: Use provisioning

Copy `provisioning/` to your Grafana config directory and the dashboard JSON files to the configured path:

```bash
cp provisioning/*.yml /etc/grafana/provisioning/datasources/
cp provisioning/dashboards.yml /etc/grafana/provisioning/dashboards/
cp cortex-*.json /var/lib/grafana/dashboards/
```

### Option 3: Docker Compose

Use the monitoring compose file:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up
```

## Prerequisites

Start the Cortex server with metrics enabled:

```bash
cortex serve context.json --enable-metrics
```

This exposes a Prometheus-compatible `/metrics` endpoint on the server port.

## Metrics Reference

These dashboards visualize the following 17 Prometheus metrics:

**Core:**
- `cortex_http_requests_total` — Total HTTP requests (method, path, status)
- `cortex_http_request_duration_seconds` — Request latency histogram
- `cortex_http_requests_in_flight` — Current in-flight requests
- `cortex_grants_active` — Active grant tokens
- `cortex_graph_nodes` — Number of graph nodes
- `cortex_graph_edges` — Number of graph edges
- `cortex_errors_total` — Errors by type
- `cortex_build_info` — Build version info

**Extended:**
- `cortex_rate_limit_rejected_total` — Rate-limited requests
- `cortex_webhook_deliveries_total` — Webhook delivery attempts
- `cortex_webhook_dead_letters` — Dead-letter queue depth
- `cortex_circuit_breaker_state` — Circuit breaker state per webhook
- `cortex_audit_entries_total` — Audit ledger entries
- `cortex_cache_hits_total` — ETag cache hits
- `cortex_cache_misses_total` — ETag cache misses
- `cortex_sse_subscribers_active` — Connected SSE clients
- `cortex_sse_events_total` — SSE events broadcast
