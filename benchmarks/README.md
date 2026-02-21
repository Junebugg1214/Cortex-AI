# Cortex Load Testing

Locust-based load testing for the Cortex CaaS API.

## Prerequisites

```bash
pip install locust
```

## Running

Start a Cortex CaaS server:

```bash
cortex serve context.json
```

In another terminal, run benchmarks:

```bash
# Web UI (default: http://localhost:8089)
locust -f benchmarks/locustfile.py --host http://127.0.0.1:8421

# Headless mode — 100 users, 10/s spawn rate, 60s duration
locust -f benchmarks/locustfile.py \
  --host http://127.0.0.1:8421 \
  --headless -u 100 -r 10 -t 60s
```

## Scenarios

| Scenario | Read/Write | Weight | Description |
|----------|-----------|--------|-------------|
| `ReadHeavyUser` | 80/20 | 3 | Health, stats, paginated nodes, search |
| `WriteHeavyUser` | 30/70 | 1 | Node/edge CRUD, deletion |
| `MixedUser` | 50/50 | 2 | Balanced full-surface coverage |

## Baseline Targets

| Metric | Target |
|--------|--------|
| p50 latency | < 50ms |
| p99 latency | < 500ms |
| Error rate | < 0.1% |
| Throughput | > 200 rps (single instance) |

## Custom Scenarios

Add new scenario files to `benchmarks/scenarios/` following the mixin pattern.
Each scenario class should use `@task(weight)` decorators for distribution.
