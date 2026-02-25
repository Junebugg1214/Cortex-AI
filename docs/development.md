# Development Guide

## Local Development Setup

```bash
# Clone the repo
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI

# Install in development mode with test dependencies
pip install -e ".[dev]"

# Verify installation
cortex --help
python3 -m pytest tests/ -q
```

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `cortex/` | Core library — extraction, graph, CLI, UPAI protocol |
| `cortex/caas/` | Context-as-a-Service HTTP API server |
| `cortex/upai/` | UPAI protocol — identity, tokens, RBAC, disclosure |
| `sdk/typescript/` | TypeScript SDK (`@cortex_ai/sdk`) |
| `sdk/python/` | Python SDK (stdlib-only) |
| `tests/` | All tests (2,361+ pytest) |
| `spec/` | UPAI protocol spec and OpenAPI definition |
| `deploy/` | Docker, Helm, Terraform, Grafana, config examples |
| `deploy/helm/` | Kubernetes Helm chart |
| `deploy/terraform/` | AWS (ECS Fargate) + GCP (Cloud Run) modules |
| `deploy/grafana/` | 3 Grafana dashboard JSON files |
| `examples/` | Sample scripts and integration patterns |
| `docs/` | Documentation |

## Running Tests

```bash
# Full test suite
python3 -m pytest tests/

# Specific test file
python3 -m pytest tests/test_graph.py

# With verbose output
python3 -m pytest tests/ -v

# Stop on first failure
python3 -m pytest tests/ -x
```

### PostgreSQL Tests

35 tests require a running PostgreSQL instance. They are skipped by default:

```bash
# To run postgres tests:
pip install "psycopg[binary]"
# Ensure a database is available at the default conninfo
python3 -m pytest tests/test_postgres_store.py tests/test_postgres_audit.py -v
```

## Storage Backends

Cortex supports three storage backends:

| Backend | Dependency | Use Case |
|---------|-----------|----------|
| JSON | None (stdlib) | Development, small deployments |
| SQLite | None (stdlib) | Single-server production |
| PostgreSQL | `psycopg[binary]` | Multi-server production |

All backends implement the abstract interfaces in `cortex/caas/storage.py`.

## Adding a New Storage Backend

1. Create a new file in `cortex/caas/` (e.g., `mysql_store.py`)
2. Implement the abstract classes from `cortex/caas/storage.py`:
   - `AbstractGrantStore`
   - `AbstractWebhookStore`
   - `AbstractAuditLog`
   - `AbstractPolicyStore`
3. Add tests in `tests/`
4. Wire it into `cortex/caas/server.py` and `cortex/cli.py`

## CaaS Server Development

```bash
# Initialize identity
cortex identity --init --name "dev"

# Start the server
cortex serve context.json --port 8421 --enable-sse --enable-metrics

# Create a grant token
cortex grant --create --audience "test-app" --policy professional
```

## Configuration

The server reads configuration from INI files with environment variable overrides:

```ini
[server]
host = 127.0.0.1
port = 8421

[storage]
backend = json

[metrics]
enabled = true

[logging]
level = DEBUG
format = json
```

Environment variables follow the pattern `CORTEX_<SECTION>_<KEY>`:
```bash
export CORTEX_SERVER_PORT=9000
export CORTEX_METRICS_ENABLED=true
```

## TypeScript SDK

```bash
cd sdk/typescript
npm install
npm test          # Runs node:test suite (33 tests)
npm run build     # ESM + CJS dual build
```

The TypeScript SDK (`@cortex_ai/sdk`) has zero runtime dependencies and uses native `fetch`.

## Code Style

- **Line length**: 120 characters
- **Linting**: ruff (E, F, W, I rules)
- **Quotes**: double quotes
- **Target**: Python 3.10+
- **Type hints**: required on all public APIs
- **Dependencies**: zero for core, optional for extras
