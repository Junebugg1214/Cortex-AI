# Cortex CaaS Deployment Guide

## Quick Start with Docker

```bash
# 1. Initialize identity and context
cortex identity --init --name "Your Name"
cortex migrate your-export.json -o context.json

# 2. Copy files to data directory
mkdir -p data/.cortex
cp context.json data/
cp .cortex/identity.json data/.cortex/

# 3. Launch
docker compose up -d
```

The server will be available at `http://localhost:8421`.

## Docker Compose

The included `docker-compose.yml` runs Cortex with SQLite persistence, JSON container logging, and the config file mounted read-only:

```yaml
services:
  cortex:
    build: .
    ports:
      - "8421:8421"
    volumes:
      - cortex-data:/data
      - ./deploy/cortex.ini:/etc/cortex/cortex.ini:ro
    env_file:
      - deploy/.env.example
    environment:
      - CORTEX_LOGGING_FORMAT=json
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    restart: unless-stopped
```

Data is stored in a Docker volume (`cortex-data`), persisting across restarts. The container runs as a non-root `cortex` user (UID 1000).

## Configuration System

Cortex uses an INI-based configuration file (`cortex.ini`) with environment variable overrides.

### Config File Format

```ini
[server]
host = 0.0.0.0
port = 8421

[storage]
backend = sqlite

[logging]
level = INFO
format = text

[security]
csrf_enabled = true
ssrf_protection = true
content_type_validation = true

[sse]
enabled = false
buffer_size = 1000

[webhooks]
max_retries = 5
circuit_breaker_threshold = 5
dead_letter_enabled = true
```

See `deploy/cortex.ini` for the full reference with comments.

### Loading Precedence

1. **Defaults** — hardcoded sensible defaults
2. **Config file** — `cortex serve --config cortex.ini` or `CORTEX_CONFIG_FILE` env var
3. **Environment variables** — `CORTEX_<SECTION>_<KEY>` overrides any config file value

### Environment Variable Convention

Every config key can be overridden with an environment variable:

```
[section]
key = value  →  CORTEX_SECTION_KEY=value
```

Examples:
- `[server] port = 9000` → `CORTEX_SERVER_PORT=9000`
- `[logging] format = json` → `CORTEX_LOGGING_FORMAT=json`
- `[security] csrf_enabled = true` → `CORTEX_SECURITY_CSRF_ENABLED=true`

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTEX_SERVER_HOST` | `127.0.0.1` | Bind address |
| `CORTEX_SERVER_PORT` | `8421` | Server port |
| `CORTEX_STORAGE_BACKEND` | `json` | Storage backend (`json` or `sqlite`) |
| `CORTEX_STORAGE_DB_PATH` | `<store-dir>/cortex.db` | SQLite database path |
| `CORTEX_LOGGING_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `CORTEX_LOGGING_FORMAT` | `text` | Log format (`text` or `json`) |
| `CORTEX_SECURITY_CSRF_ENABLED` | `true` | Enable CSRF token validation |
| `CORTEX_SECURITY_SSRF_PROTECTION` | `true` | Block requests to private/internal IPs |
| `CORTEX_SECURITY_CONTENT_TYPE_VALIDATION` | `true` | Enforce Content-Type on POST/PUT |
| `CORTEX_SSE_ENABLED` | `false` | Enable Server-Sent Events endpoint |
| `CORTEX_SSE_BUFFER_SIZE` | `1000` | Max events retained for replay |
| `CORTEX_WEBHOOKS_MAX_RETRIES` | `5` | Max delivery retries per webhook event |
| `CORTEX_WEBHOOKS_CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before circuit opens |
| `CORTEX_WEBHOOKS_DEAD_LETTER_ENABLED` | `true` | Enable dead-letter queue |
| `CORTEX_CONFIG_FILE` | *(none)* | Path to cortex.ini (alternative to `--config`) |

## Structured Logging

Cortex supports two log formats configured via `[logging]` in `cortex.ini`:

### Text Format (default)

Human-readable, suitable for development:

```
2026-02-20 14:30:00 INFO  [req-abc123] POST /context 200 12ms
2026-02-20 14:30:01 DEBUG [req-abc124] Grant verified: grant_id=abc...
```

### JSON Format (recommended for containers)

Machine-parseable, suitable for log aggregation (ELK, Loki, CloudWatch):

```json
{"timestamp":"2026-02-20T14:30:00Z","level":"INFO","request_id":"req-abc123","method":"POST","path":"/context","status":200,"duration_ms":12}
```

### Configuration

```ini
[logging]
level = INFO     # DEBUG, INFO, WARNING, ERROR, CRITICAL
format = json    # text or json
```

Or via environment:
```bash
CORTEX_LOGGING_LEVEL=DEBUG CORTEX_LOGGING_FORMAT=json cortex serve context.json
```

## Graceful Shutdown

Cortex uses a `ShutdownCoordinator` that handles SIGTERM and SIGINT signals:

1. Signal received → stops accepting new connections
2. In-flight requests complete (up to 30s timeout)
3. SSE connections are drained
4. Webhook workers finish current deliveries
5. Database connections are closed
6. Process exits cleanly

Expected log output on shutdown:
```
INFO  Shutdown signal received, draining connections...
INFO  Waiting for 3 in-flight requests...
INFO  All connections drained, shutting down.
```

### Systemd Coordination

The systemd unit (`deploy/cortex.service`) sets `TimeoutStopSec=30` to match the coordinator's drain timeout. This ensures systemd waits for graceful shutdown before sending SIGKILL.

## VPS Deployment

### Prerequisites

- Python 3.9+
- A context JSON file
- An initialized UPAI identity (`.cortex/identity.json`)

### Install

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
pip install .
```

### Run with Config File

```bash
# Copy and customize config
cp deploy/cortex.ini /etc/cortex/cortex.ini

# Start with config
cortex serve context.json \
    --config /etc/cortex/cortex.ini \
    --storage sqlite \
    --db-path /var/lib/cortex/cortex.db \
    --store-dir /var/lib/cortex/.cortex
```

### Systemd Service

A standalone systemd unit is provided at `deploy/cortex.service`. Install it:

```bash
sudo cp deploy/cortex.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cortex
sudo systemctl start cortex
```

The unit includes security hardening:
- `NoNewPrivileges=true` — prevents privilege escalation
- `ProtectSystem=strict` — read-only filesystem except allowed paths
- `ProtectHome=true` — hides /home from the process
- `PrivateTmp=true` — isolated /tmp namespace
- `TimeoutStopSec=30` — matches ShutdownCoordinator drain timeout

Check status:
```bash
sudo systemctl status cortex
journalctl -u cortex -f
```

## Reverse Proxy

### Caddy (recommended)

Caddy provides automatic TLS via Let's Encrypt with zero configuration:

```bash
# Install Caddy
# See: https://caddyserver.com/docs/install

# Edit the Caddyfile
cp deploy/Caddyfile /etc/caddy/Caddyfile
# Replace your-domain.example.com with your domain

# Start
sudo systemctl enable caddy
sudo systemctl start caddy
```

The included `deploy/Caddyfile` handles:
- Automatic HTTPS via Let's Encrypt
- SSE streaming (`flush_interval -1`)
- Security headers (HSTS, CSP, X-Content-Type-Options)
- 1 MB request body limit

### Nginx

Copy `deploy/nginx.conf` and update:

1. Replace `your-domain.example.com` with your domain
2. Set up TLS certificates (e.g., via Let's Encrypt):
   ```bash
   sudo certbot --nginx -d your-domain.example.com
   ```
3. Reload nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

The nginx config includes a dedicated `/events` location block for SSE with:
- `proxy_buffering off` — disables response buffering
- `proxy_cache off` — bypasses cache
- `proxy_read_timeout 86400s` — allows long-lived connections
- `X-Accel-Buffering no` — disables nginx internal buffering

## Security Features

### CSRF Protection

Enabled by default (`csrf_enabled = true`). State-changing requests (POST, PUT, DELETE) require a valid CSRF token obtained from the `/csrf-token` endpoint.

### SSRF Protection

Enabled by default (`ssrf_protection = true`). Blocks webhook deliveries and outbound requests to private/internal IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1, etc.).

### Content-Type Validation

Enabled by default (`content_type_validation = true`). POST and PUT requests must include a valid `Content-Type: application/json` header.

### Field Encryption at Rest

Sensitive fields in the SQLite store can be encrypted using AES-256-GCM. Set the encryption key via environment variable:

```bash
CORTEX_ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

### Rate Limiting

Built-in rate limiting at 60 requests/minute per IP. Configurable via the server module.

### TLS

The CaaS server does not handle TLS directly. **Always deploy behind a TLS-terminating reverse proxy** (Caddy or nginx) in production.

## Storage Backends

### JSON (default)

- Grants persisted to `<store-dir>/grants.json`
- Webhooks in-memory only (lost on restart)
- No audit log
- Best for: development, testing

### SQLite

- All data persisted to a single `.db` file
- Grants, webhooks, audit log, delivery log
- WAL mode for concurrent access
- Best for: single-server production

```bash
cortex serve context.json --storage sqlite --db-path ./cortex.db
```

### PostgreSQL

- Full relational storage for grants, webhooks, audit log, delivery log
- Connection pooling support via `psycopg_pool`
- Hash-chained audit ledger with tamper verification
- Best for: multi-server production deployments

```bash
pip install "cortex-identity[postgres]"

cortex serve context.json \
    --storage postgres \
    --db-url "host=localhost dbname=cortex user=cortex"
```

Environment variable: `CORTEX_STORAGE_DB_URL`

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTEX_STORAGE_BACKEND` | `json` | Storage backend (`json`, `sqlite`, or `postgres`) |
| `CORTEX_STORAGE_DB_URL` | *(none)* | PostgreSQL connection string (libpq format) |

## Infrastructure as Code

### Helm Chart (Kubernetes)

A full Helm chart is provided at `deploy/helm/cortex/`:

```bash
helm install cortex deploy/helm/cortex \
    --set storage.backend=postgres \
    --set storage.dbUrl="host=pg dbname=cortex"
```

### Terraform Modules

AWS and GCP modules are provided at `deploy/terraform/`:

```bash
# AWS — ECS Fargate + ALB
cd deploy/terraform/aws && terraform apply

# GCP — Cloud Run
cd deploy/terraform/gcp && terraform apply
```

### Grafana Dashboards

Three pre-built dashboards are available at `deploy/grafana/`:

- Import the JSON files into Grafana
- Point the Prometheus data source at the Cortex `/metrics` endpoint
- Dashboards cover: request rates, latency percentiles, storage operations, webhook delivery

## Health Check

```bash
curl http://localhost:8421/health
```

Returns:
```json
{
    "status": "ok",
    "version": "1.0.0",
    "has_identity": true,
    "has_graph": true,
    "grant_count": 0
}
```

## Cloud Deployment

### AWS ECS / EC2

```bash
# Build and push to ECR
aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
docker build -t cortex-caas .
docker tag cortex-caas:latest <account>.dkr.ecr.<region>.amazonaws.com/cortex-caas:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/cortex-caas:latest

# Or run directly on EC2
docker run -d \
    -p 8421:8421 \
    -v /data/cortex:/data \
    -e CORTEX_LOGGING_FORMAT=json \
    cortex-caas
```

### GCP Cloud Run

```bash
# Build and push to Artifact Registry
gcloud builds submit --tag gcr.io/<project>/cortex-caas

# Deploy
gcloud run deploy cortex-caas \
    --image gcr.io/<project>/cortex-caas \
    --port 8421 \
    --set-env-vars CORTEX_LOGGING_FORMAT=json \
    --allow-unauthenticated
```

### Azure Container Instances

```bash
az container create \
    --resource-group cortex-rg \
    --name cortex-caas \
    --image <registry>.azurecr.io/cortex-caas:latest \
    --ports 8421 \
    --environment-variables CORTEX_LOGGING_FORMAT=json \
    --dns-name-label cortex
```
