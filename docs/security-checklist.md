# Cortex-AI Deployment Security Checklist

Use this checklist when deploying Cortex-AI to production.

---

## Pre-Deployment

- [ ] **Install PyNaCl** — Enables Ed25519 cryptographic operations
  ```bash
  pip install pynacl
  ```
- [ ] **Generate identity** — Create Ed25519 keypair
  ```bash
  cortex identity --init --store-dir /secure/path/.cortex
  ```
- [ ] **Verify key permissions** — `identity.key` must be 0o600
  ```bash
  ls -la /secure/path/.cortex/identity.key
  # Should show: -rw-------
  ```
- [ ] **Exclude secrets from version control**
  - `identity.key` in `.gitignore`
  - Database credentials not in code
  - OAuth client secrets in environment variables

---

## Transport Security

- [ ] **TLS reverse proxy configured** (Caddy, Nginx, or cloud ALB)
- [ ] **TLS 1.2+ enforced** — Disable TLS 1.0/1.1
- [ ] **HSTS header enabled** on reverse proxy
- [ ] **Certificate auto-renewal** configured (Let's Encrypt / ACM)
- [ ] **Cortex binds to localhost only** (default `127.0.0.1`)
  - If binding to `0.0.0.0`, ensure firewall rules restrict access

---

## Authentication & Authorization

- [ ] **Grant tokens use appropriate TTL** (default 24h; shorter for sensitive operations)
- [ ] **Scopes follow least-privilege** — Don't issue `admin:all` unless necessary
- [ ] **OAuth whitelist configured** — Restrict `--oauth-allowed-email` to known users
- [ ] **CSRF enabled** for dashboard (`csrf_enabled = true` in config)
- [ ] **Revoke unused grants** — Audit active grants periodically
  ```bash
  cortex grant --list --store-dir /path/.cortex
  ```

---

## Network Security

- [ ] **CORS origins restricted** — Set `--allowed-origins` to known domains only
- [ ] **SSRF protection enabled** — `ssrf_block_private = true` (default)
- [ ] **Rate limiting configured** — Appropriate for expected traffic
- [ ] **Firewall rules** — Only reverse proxy can reach Cortex port (8421)
- [ ] **No direct internet exposure** — Cortex should not be publicly reachable without proxy

---

## Data Protection

- [ ] **Disclosure policies configured** — Default to `professional` or `public`, not `full`
- [ ] **PII reviewed** — Understand what personal data is in your context graph
- [ ] **Max body size set** — Prevent oversized request abuse
  ```ini
  [server]
  max_body_size = 1048576
  ```
- [ ] **Database encrypted at rest** (encrypted volume, RDS encryption, Cloud SQL encryption)

---

## Audit & Monitoring

- [ ] **Audit ledger enabled** — Verify chain integrity regularly
  ```bash
  curl http://localhost:8421/audit/verify
  ```
- [ ] **Structured logging enabled** — JSON format for SIEM ingestion
  ```ini
  [logging]
  level = INFO
  format = json
  ```
- [ ] **Prometheus metrics enabled** — Monitor request rates, errors, latencies
  ```bash
  cortex serve context.json --enable-metrics
  ```
- [ ] **Grafana dashboards imported** — `deploy/grafana/*.json`
- [ ] **Alerting configured** — Alert on:
  - Error rate > 5%
  - p99 latency > 1s
  - Audit chain verification failure
  - Circuit breaker open
  - Dead letter queue growth

---

## Federation (if enabled)

- [ ] **Trust list curated** — Only add verified peer DIDs
- [ ] **Export signing enabled** — `sign_exports = true` (default)
- [ ] **Bundle TTL appropriate** — Default 1 hour; shorter for sensitive data
- [ ] **Export policy set** — Use `summary` or `minimal` unless full sharing is needed
- [ ] **Review imported data** — Federation imports merge into local graph

---

## Webhook Security

- [ ] **SSRF protection active** — Webhook URLs validated against private ranges
- [ ] **Circuit breaker configured** — Prevent cascading failures
  ```ini
  [webhooks]
  circuit_failure_threshold = 5
  circuit_cooldown = 60
  ```
- [ ] **Dead letter queue monitored** — Failed deliveries are logged and retrievable
- [ ] **Webhook secrets rotated** — If using webhook signatures

---

## Key Rotation

- [ ] **Key rotation schedule defined** — Recommended: quarterly or after personnel changes
- [ ] **Rotation procedure documented:**
  ```bash
  # 1. Rotate key
  cortex keychain --rotate --store-dir /path/.cortex

  # 2. Update federation peers with new DID

  # 3. Re-issue grants with new identity

  # 4. Verify rotation chain
  cortex keychain --verify --store-dir /path/.cortex
  ```
- [ ] **Compromised key procedure documented:**
  ```bash
  cortex keychain --rotate --reason compromised --store-dir /path/.cortex
  ```

---

## PostgreSQL Backend (if used)

- [ ] **SSL connection required** — `sslmode=require` or `sslmode=verify-full`
- [ ] **Dedicated database user** — Not superuser; limited to cortex database
- [ ] **Connection pooling configured** — Prevent connection exhaustion
- [ ] **Regular backups** — pg_dump or WAL archiving
- [ ] **Connection string not in code** — Use environment variable:
  ```bash
  export CORTEX_STORAGE_DB_URL="host=db.example.com dbname=cortex user=cortex password=*** sslmode=require"
  ```

---

## Container/Cloud Deployment

- [ ] **Non-root container user** — Don't run as root in Docker
- [ ] **Read-only filesystem** where possible (except data volume)
- [ ] **Resource limits set** — CPU and memory limits in Kubernetes/ECS/Cloud Run
- [ ] **Health checks configured** — `/health` endpoint
- [ ] **Secrets management** — Use cloud secrets manager (AWS Secrets Manager, GCP Secret Manager)
- [ ] **Image scanning** — Scan container images for vulnerabilities
- [ ] **Network policies** — Restrict pod-to-pod communication in Kubernetes

---

## Periodic Review

- [ ] **Monthly:** Review active grants and revoke unused
- [ ] **Monthly:** Verify audit ledger integrity
- [ ] **Quarterly:** Rotate identity keys
- [ ] **Quarterly:** Review federation trust list
- [ ] **Quarterly:** Update dependencies (PyNaCl, psycopg)
- [ ] **Annually:** Full security review against this checklist
