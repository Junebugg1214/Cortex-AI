# Cortex-AI Threat Model (STRIDE Analysis)

## Scope

This threat model covers the Cortex-AI CaaS (Context as a Service) API server, including the UPAI identity layer, graph storage, and federation subsystem.

## System Context Diagram

```
                    ┌─────────────┐
                    │  Reverse    │
 Clients ──────────▶│  Proxy      │──────────▶ Cortex CaaS Server
 (SDK/CLI/Browser)  │  (TLS)      │            ├── Identity (Ed25519)
                    └─────────────┘            ├── Graph (SQLite/PG)
                                               ├── Audit Ledger
                                               ├── Webhook Worker
                          ┌────────────────────├── Federation Manager
                          │                    └── Metrics
                          ▼
                    ┌─────────────┐
                    │  Federation │
                    │  Peer       │
                    └─────────────┘
```

## Trust Boundaries

1. **External → Reverse Proxy:** Untrusted internet traffic
2. **Reverse Proxy → Cortex:** Trusted internal network
3. **Cortex → Database:** Trusted local storage
4. **Cortex → Webhook Targets:** Semi-trusted external services
5. **Cortex → Federation Peers:** Explicitly trusted instances

---

## STRIDE Analysis

### S — Spoofing

| Threat | Risk | Controls |
|--------|------|----------|
| Attacker forges a grant token | High | Ed25519 signature verification on every request; tokens bound to issuer DID |
| Attacker replays a valid token | Medium | Nonce cache prevents token reuse; TTL expiry limits window |
| Attacker impersonates a federation peer | High | Trust list of known DIDs; Ed25519 signature on bundles |
| Attacker steals private key file | High | File permissions (0o600); key never leaves disk; recommend encrypted volumes |
| Attacker performs MITM | High | TLS termination at reverse proxy (external control) |

**Residual Risk:** Without PyNaCl, HMAC-SHA256 fallback cannot be verified remotely — federation requires Ed25519.

### T — Tampering

| Threat | Risk | Controls |
|--------|------|----------|
| Attacker modifies audit ledger entries | High | Hash-chained SHA-256; `GET /audit/verify` detects chain breaks |
| Attacker modifies data in transit | Medium | TLS at reverse proxy; Ed25519 signatures on tokens/bundles |
| Attacker tampers with federation bundle | High | Content hash (SHA-256) verified on import; signature verification |
| SQL injection modifies stored data | Medium | Parameterized queries only; no string interpolation in SQL |
| Attacker modifies config file | Medium | File system permissions; environment variable overrides are explicit |

### R — Repudiation

| Threat | Risk | Controls |
|--------|------|----------|
| User denies performing an action | Medium | Audit ledger records actor DID, action, timestamp, details |
| Attacker deletes audit entries | Medium | Hash chain detects missing entries; PostgreSQL backend supports WAL archiving |
| Federation import source disputed | Low | Bundle includes exporter DID and signature |

### I — Information Disclosure

| Threat | Risk | Controls |
|--------|------|----------|
| Unauthorized access to graph data | High | Grant tokens required; disclosure policies filter exposed fields |
| Oversharing via federation | Medium | Export policies (minimal/summary/full); tag filtering |
| PII leakage in API responses | Medium | PII redactor; disclosure policies; operators configure field restrictions |
| Error messages leak internals | Low | Standardized error format; no stack traces in production responses |
| Timing attacks on token verification | Low | Constant-time comparison via `hmac.compare_digest` |

### D — Denial of Service

| Threat | Risk | Controls |
|--------|------|----------|
| Request flooding | Medium | Token-bucket rate limiter per IP; `429 Too Many Requests` |
| Large request bodies | Medium | Configurable `max_body_size` (default 1 MiB) |
| Webhook loop/amplification | Medium | Circuit breaker on webhook delivery; dead-letter queue |
| Resource exhaustion via search | Low | LIMIT clauses on all queries; pagination enforced |
| Federation bundle flooding | Low | Nonce dedup; expiry check; trust list filters |

### E — Elevation of Privilege

| Threat | Risk | Controls |
|--------|------|----------|
| Token with broader scopes than intended | Medium | Scopes explicitly declared at grant creation; RBAC enforcement per endpoint |
| Viewer escalates to admin | High | Scope hierarchy enforced server-side; no client-side scope trust |
| OAuth token grants excessive access | Medium | OAuth token mapped to specific role; `oauth_allowed_emails` whitelist |
| Plugin executes arbitrary code | Medium | Plugins run in-process; errors caught and logged, not propagated; operator must explicitly enable plugins |

---

## Attack Scenarios

### Scenario 1: Stolen Grant Token

1. Attacker obtains a valid grant token (e.g., from logs, insecure storage)
2. Attacker uses token to access API
3. **Mitigations:** Token TTL limits exposure window; nonce prevents replay; revocation via `DELETE /grants/<id>` immediately invalidates; audit log records all access

### Scenario 2: Compromised Private Key

1. Attacker obtains `identity.key` file
2. Attacker can sign new tokens and impersonate the instance
3. **Mitigations:** Key rotation via `cortex keychain --rotate` generates new identity and revocation proof; old tokens become invalid; federation peers must update trust list

### Scenario 3: Malicious Federation Peer

1. Trusted peer's instance is compromised
2. Attacker sends crafted bundle to import malicious graph data
3. **Mitigations:** Content hash verification detects tampering; signature verification ensures bundle origin; remove compromised DID from trust list; imported nodes are regular graph entries (no code execution)

### Scenario 4: Webhook SSRF

1. Attacker creates webhook pointing to internal service
2. Cortex delivers events to internal endpoint
3. **Mitigations:** SSRF protection blocks private IP ranges by default; circuit breaker prevents sustained abuse; webhook creation requires `manage:webhooks` scope

---

## Recommendations

### Critical

1. **Always deploy behind TLS-terminating reverse proxy** — Cortex does not handle TLS
2. **Install PyNaCl** for Ed25519 cryptography — HMAC fallback cannot verify remote signatures
3. **Set file permissions** on `identity.key` to 0o600
4. **Configure rate limiting** appropriate to expected load
5. **Enable CSRF** for dashboard access (`csrf_enabled = true`)

### Important

6. Review and configure disclosure policies before exposing API
7. Regularly verify audit chain integrity (`GET /audit/verify`)
8. Rotate keys periodically via `cortex keychain --rotate`
9. Monitor webhook dead-letter queue for delivery failures
10. Use PostgreSQL backend in production for durability

### Operational

11. Enable structured JSON logging for SIEM integration
12. Deploy Prometheus + Grafana for real-time monitoring
13. Set `max_body_size` appropriate to expected payload sizes
14. Restrict `--allowed-origins` to known client domains
15. Review federation trust list regularly
