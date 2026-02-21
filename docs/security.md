# Cortex-AI Security Architecture

## Overview

Cortex-AI implements defense-in-depth security across authentication, authorization, transport, data protection, and audit. This document describes the security model for operators conducting security assessments.

---

## 1. Identity & Authentication

### DID-Based Identity

Every Cortex instance has a cryptographic identity rooted in a **did:key** Decentralized Identifier.

- **Key type:** Ed25519 (via PyNaCl when available; HMAC-SHA256 stdlib fallback)
- **DID format:** `did:key:z6Mk...` — multicodec-encoded Ed25519 public key
- **Key storage:**
  - Public: `identity.json` (safe to commit)
  - Private: `identity.key` (mode 0o600, excluded from version control)
- **Key rotation:** Supported via `cortex keychain --rotate` with cryptographic proof chain linking old → new keys

### Grant Tokens

API access is controlled through **grant tokens** — Ed25519-signed JWS tokens containing:

| Field | Description |
|-------|-------------|
| `iss` | Issuer DID |
| `sub` | Subject/audience |
| `iat` | Issued-at timestamp |
| `exp` | Expiry timestamp |
| `nonce` | Unique nonce (replay protection) |
| `scope` | Authorized scopes (e.g., `read:context`, `write:nodes`) |
| `policy` | Disclosure policy name |

**Token lifecycle:**
1. Created via `POST /grants` or `cortex grant --create`
2. Presented in `Authorization: Bearer <token>` header
3. Verified on every request: signature, expiry, nonce, scope
4. Revoked via `DELETE /grants/<id>` or `cortex grant --revoke`

### Nonce Cache

A server-side `NonceCache` prevents token replay attacks:
- Each nonce can only be used once
- Nonces expire after the token's TTL
- Cache is thread-safe (uses `threading.Lock`)

---

## 2. Authorization (RBAC)

### Role Model

Four hierarchical roles control access:

| Role | Description | Scopes |
|------|-------------|--------|
| `viewer` | Read-only access | `read:context`, `read:identity` |
| `editor` | Read + write nodes/edges | viewer + `write:nodes`, `write:edges`, `read:audit` |
| `admin` | Full management | editor + `manage:grants`, `manage:webhooks`, `manage:policies` |
| `owner` | Instance owner | admin + `admin:all` |

### Scope Enforcement

Every API endpoint requires specific scopes:

| Endpoint | Required Scope |
|----------|---------------|
| `GET /context/*` | `read:context` |
| `POST /context/nodes` | `write:nodes` |
| `POST /context/edges` | `write:edges` |
| `POST /grants` | `manage:grants` |
| `DELETE /grants/*` | `manage:grants` |
| `GET /audit` | `read:audit` |
| `POST /webhooks` | `manage:webhooks` |
| `POST /policies` | `manage:policies` |
| `GET /metrics` | `read:metrics` |

Unauthenticated requests receive: `GET /health`, `GET /`, `GET /.well-known/upai-configuration`.

### Disclosure Policies

Policies control what data is exposed through grants:

- **full:** All node fields, properties, descriptions, timeline
- **professional:** Exclude personal lifestyle data
- **public:** Only public-safe fields (label, tags, brief)
- **minimal:** Labels and tags only (no confidence, no properties)
- **custom:** User-defined field filters via `POST /policies`

---

## 3. Transport Security

### TLS Termination

Cortex-AI runs as a plain HTTP server. **TLS must be terminated by a reverse proxy.**

Recommended configurations:

**Caddy (simplest):**
```
cortex.example.com {
    reverse_proxy localhost:8421
}
```

**Nginx:**
```nginx
server {
    listen 443 ssl;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {
        proxy_pass http://127.0.0.1:8421;
    }
}
```

### CORS

Configurable allowed origins via `--allowed-origins` or config file. Defaults to localhost only. Uses:
- `Access-Control-Allow-Origin`
- `Access-Control-Allow-Methods`
- `Access-Control-Allow-Headers`
- Preflight caching (`Access-Control-Max-Age: 86400`)

### CSRF Protection

Dashboard mutations require a CSRF token when `csrf_enabled = true`:
- Token generated on login and stored in session
- Verified on all state-changing dashboard API calls
- Enabled by default when config file is provided

---

## 4. Data Protection

### Input Validation

- **Max body size:** Configurable (`max_body_size`, default 1 MiB)
- **Content-Type enforcement:** JSON endpoints reject non-JSON bodies
- **Node/Edge validation:** Required fields checked before persistence
- **Query parameter sanitization:** URL-decoded and validated

### PII Handling

- **PII Redactor:** Built-in redaction engine for email, phone, SSN, address patterns
- **Disclosure policies:** Control PII exposure at the API layer
- **Node properties:** Can store arbitrary data — operators must configure policies to restrict sensitive fields

### SSRF Protection

When `ssrf_block_private = true` (default):
- Webhook delivery URLs are validated against RFC 1918/RFC 6598 ranges
- Prevents internal network scanning via webhook configuration
- Blocks: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `127.0.0.0/8`

### SQL Injection Prevention

- SQLite and PostgreSQL backends use parameterized queries exclusively
- No string interpolation in SQL statements
- Connection parameters passed via psycopg's native parameter binding

---

## 5. Audit & Accountability

### Hash-Chained Audit Ledger

Every state-changing operation is recorded in a tamper-evident audit log:

```
Entry N:
  id:        <UUID>
  timestamp: <ISO-8601>
  actor:     <DID or "system">
  action:    <create_node|delete_edge|create_grant|...>
  resource:  <resource identifier>
  details:   <JSON payload>
  prev_hash: <SHA-256 of Entry N-1>
  hash:      SHA-256(id + timestamp + actor + action + resource + details + prev_hash)
```

**Verification:** `GET /audit/verify` walks the entire chain and reports any broken links.

**Storage backends:**
- SQLite: `audit_ledger` table
- PostgreSQL: `cortex_audit_ledger` table with indexes on actor, action, timestamp

### Structured Logging

- Request correlation IDs (`X-Request-ID`) propagated through all log entries
- Configurable level (DEBUG/INFO/WARNING/ERROR) and format (text/JSON)
- Thread-local context for request-scoped metadata

---

## 6. Rate Limiting

Token-bucket rate limiter per client IP:
- Default: 100 requests/minute
- Configurable via config file
- Returns `429 Too Many Requests` with `Retry-After` header
- Thread-safe implementation

---

## 7. Cryptographic Operations Summary

| Operation | Algorithm | Library |
|-----------|-----------|---------|
| Identity key generation | Ed25519 | PyNaCl (optional) |
| Token signing | Ed25519 | PyNaCl |
| Token verification | Ed25519 | PyNaCl |
| Fallback signing | HMAC-SHA256 | stdlib `hmac` |
| Audit chain | SHA-256 | stdlib `hashlib` |
| Nonce generation | CSPRNG | stdlib `secrets` |
| DID encoding | Base58btc | stdlib (custom implementation) |
| Token encoding | Base64url | stdlib `base64` |
| Password hashing | N/A | Not applicable (no passwords) |

---

## 8. Federation Security

Cross-instance context sharing adds additional security surfaces:

- **Signed bundles:** Graph exports are Ed25519-signed
- **Trust list:** Only bundles from trusted DIDs are accepted
- **Replay protection:** Per-bundle nonces tracked server-side
- **Content integrity:** SHA-256 hash of graph data verified on import
- **Expiry:** Bundles have configurable TTL (default: 1 hour)
- **Policy filtering:** Exports can use minimal/summary/full policies to control data exposure

---

## 9. Dependency Security

Cortex-AI follows a **zero mandatory external dependency** policy:
- Core functionality uses Python stdlib only
- PyNaCl is optional (enables Ed25519; falls back to HMAC-SHA256)
- psycopg is optional (enables PostgreSQL; SQLite is default)
- No web framework dependencies (uses stdlib `http.server`)

This dramatically reduces supply chain attack surface.

---

## 10. Known Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| No TLS termination | Traffic unencrypted without reverse proxy | Deploy behind Caddy/Nginx/ALB |
| Single-process model | No horizontal scaling of writes | Use PostgreSQL backend for shared state |
| HMAC fallback | No remote signature verification | Install PyNaCl for Ed25519 |
| In-memory nonce cache | Nonces lost on restart | Token TTLs provide eventual replay protection |
| No key encryption at rest | Private key file readable by process owner | Use file permissions (0o600) + encrypted volume |
| No WAF integration | No automatic request filtering | Deploy behind cloud WAF (AWS WAF, Cloud Armor) |
