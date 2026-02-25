# Cortex Load Testing & Profiling

Locust-based load testing and profiling tools for the Cortex CaaS API.

## Prerequisites

```bash
pip install locust
```

## Running Load Tests

Start a Cortex CaaS server:

```bash
cortex serve context.json
```

In another terminal, run benchmarks:

```bash
# Web UI (default: http://localhost:8089)
locust -f benchmarks/locustfile.py --host http://127.0.0.1:8421

# With authentication
locust -f benchmarks/locustfile.py --host http://127.0.0.1:8421 \
  --token YOUR_GRANT_TOKEN

# Headless mode — 100 users, 10/s spawn rate, 60s duration
locust -f benchmarks/locustfile.py \
  --host http://127.0.0.1:8421 \
  --headless -u 100 -r 10 -t 60s \
  --token YOUR_GRANT_TOKEN
```

## Scenarios

| Scenario | Read/Write | Weight | Description |
|----------|-----------|--------|-------------|
| `ReadHeavyUser` | 80/20 | 3 | Health, stats, paginated nodes, search, ETag caching |
| `WriteHeavyUser` | 30/70 | 1 | Node/edge CRUD, deletion |
| `MixedUser` | 50/50 | 2 | Balanced full-surface coverage, versions, health |
| `AuthFlowUser` | 50/50 | 2 | Authenticated flows: context, versions, neighbors |

## Baseline Targets

| Metric | Target |
|--------|--------|
| p50 latency | < 50ms |
| p99 latency | < 500ms |
| Error rate | < 0.1% |
| Throughput | > 200 rps (single instance) |

## Profiling Scripts

### Memory Profiling

Profile peak memory usage of graph operations using stdlib `tracemalloc`:

```bash
python3 benchmarks/profile_memory.py
python3 benchmarks/profile_memory.py --nodes 5000 --edges 10000
```

### ETag Benchmark

Measure ETag cache hit rate and latency savings:

```bash
python3 benchmarks/benchmark_etag.py
python3 benchmarks/benchmark_etag.py --url http://127.0.0.1:8421 --requests 200
python3 benchmarks/benchmark_etag.py --token YOUR_GRANT_TOKEN
```

## Custom Scenarios

Add new scenario files to `benchmarks/scenarios/` following the mixin pattern.
Each scenario class should use `@task(weight)` decorators for distribution.
Use `on_start()` to pick up the auth token from `benchmarks.locustfile._AUTH_TOKEN`.
