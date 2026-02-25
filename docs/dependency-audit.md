# Dependency Audit

Last reviewed: 2026-02-25

## Core Dependencies (Zero Runtime Dependencies)

Cortex-AI's core (`cortex/` package) has **zero required external dependencies**. All cryptographic helpers (base58btc, base64url, SHA-256 hashing) use Python stdlib only.

| Component | Dependencies | Notes |
|-----------|-------------|-------|
| Graph engine | None | Pure Python, stdlib only |
| UPAI protocol | None | Identity, tokens, schemas — all stdlib |
| CaaS server | None | `http.server`, `json`, `sqlite3` — all stdlib |
| CLI | None | `argparse` — stdlib |

## Optional Dependencies

| Package | Version | Purpose | When Required |
|---------|---------|---------|---------------|
| `pynacl` | >=1.5.0 | Ed25519 cryptographic operations | Identity generation, token signing |
| `psycopg[binary]` | >=3.0 | PostgreSQL backend | `--storage postgres` |
| `numpy` | >=1.20 | Semantic search vector operations | Semantic search plugin |

### Security Notes

- **pynacl**: Wraps libsodium. Well-audited, widely used. Pin to latest patch.
- **psycopg**: Official PostgreSQL adapter for Python. Use `sslmode=require` or `verify-full` in production.
- **numpy**: Large dependency surface. Only loaded when semantic search is enabled.

## Development Dependencies

| Package | Purpose |
|---------|---------|
| `pytest` | Test runner |
| `pytest-cov` | Coverage reporting |

## TypeScript SDK Dependencies (`sdk/typescript/`)

### Runtime Dependencies
None. The SDK uses native `fetch` and has zero runtime dependencies.

### Development Dependencies

| Package | Purpose |
|---------|---------|
| `typescript` | Compilation |
| `@types/node` | Node.js type definitions |

## Audit Process

### Python Dependencies

```bash
# Install pip-audit
pip install pip-audit

# Audit installed packages
pip-audit

# Audit from requirements file
pip-audit -r requirements.txt
```

### TypeScript SDK

```bash
cd sdk/typescript
npm audit

# Fix automatically where possible
npm audit fix
```

### Manual Review Checklist

- [ ] Check CVE databases for known vulnerabilities
- [ ] Review changelogs for security-relevant updates
- [ ] Verify package integrity (checksums, signatures)
- [ ] Confirm no typosquatting risk in package names
- [ ] Review transitive dependencies

## Review Schedule

| Frequency | Action |
|-----------|--------|
| Quarterly | Full dependency audit (pip-audit, npm audit) |
| Monthly | Check for critical CVEs in pynacl, psycopg |
| On release | Audit all deps before tagging a release |
| On alert | Immediate review if GitHub Dependabot alerts fire |

## Supply Chain Protections

- **Minimal surface**: Zero required runtime deps reduces attack surface
- **Pinned versions**: Production deployments should pin exact versions
- **Lock files**: Use `pip freeze > requirements.txt` and `package-lock.json`
- **Verified sources**: Only install from PyPI and npm official registries
- **GitHub Dependabot**: Enabled for automated vulnerability alerts
