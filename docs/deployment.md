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

The included `docker-compose.yml` runs Cortex with SQLite persistence:

```yaml
services:
  cortex:
    build: .
    ports:
      - "8421:8421"
    volumes:
      - cortex-data:/data
    restart: unless-stopped
```

Data is stored in a Docker volume (`cortex-data`), persisting across restarts.

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

### Run with SQLite

```bash
cortex serve context.json \
    --storage sqlite \
    --db-path /var/lib/cortex/cortex.db \
    --store-dir /var/lib/cortex/.cortex \
    --port 8421
```

### Systemd Service

```ini
# /etc/systemd/system/cortex.service
[Unit]
Description=Cortex CaaS Server
After=network.target

[Service]
Type=simple
User=cortex
WorkingDirectory=/var/lib/cortex
ExecStart=/usr/local/bin/cortex serve /var/lib/cortex/context.json \
    --storage sqlite \
    --db-path /var/lib/cortex/cortex.db \
    --store-dir /var/lib/cortex/.cortex
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable cortex
sudo systemctl start cortex
```

## Reverse Proxy (nginx)

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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTEX_PORT` | `8421` | Server port |

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
- Best for: production

```bash
cortex serve context.json --storage sqlite --db-path ./cortex.db
```

## Security Notes

- **Always use TLS in production.** The CaaS server itself does not handle TLS.
- **Rate limiting** is built-in (60 req/min per IP by default).
- **Body size** is limited to 1 MB.
- **Grant tokens** are Ed25519-signed and time-limited.
- **Webhook payloads** are HMAC-SHA256 signed.
