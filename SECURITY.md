# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.4.x   | :white_check_mark: |
| 1.3.x   | :white_check_mark: |
| < 1.3   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability in Cortex-AI, please report it responsibly.

### How to Report

**Email:** Send a detailed report to the repository maintainer via GitHub private vulnerability reporting or by opening a [security advisory](https://github.com/Junebugg1214/Cortex-AI/security/advisories/new).

**Include:**
- Description of the vulnerability
- Steps to reproduce
- Affected version(s)
- Impact assessment (what an attacker could achieve)
- Any suggested fix (optional but appreciated)

**Do NOT:**
- Open a public GitHub issue for security vulnerabilities
- Disclose the vulnerability publicly before it has been addressed
- Exploit the vulnerability against production systems

### Response Timeline

| Step | Timeline |
|------|----------|
| Acknowledgment | Within 48 hours |
| Triage and severity assessment | Within 7 days |
| Fix development | Within 30 days (critical: 7 days) |
| Coordinated disclosure | After fix is released |

### Disclosure Process

1. Reporter submits vulnerability via private channel
2. Maintainers acknowledge receipt within 48 hours
3. Maintainers assess severity and develop a fix
4. Fix is released in a patch version
5. Security advisory is published with credit to the reporter
6. Reporter may publish their own writeup after the advisory

### Severity Classification

- **Critical:** Remote code execution, authentication bypass, data exfiltration
- **High:** Privilege escalation, audit log tampering, SSRF to internal services
- **Medium:** Rate limit bypass, information disclosure (non-sensitive), XSS
- **Low:** Missing security headers, verbose error messages, minor hardening gaps

## Scope

### In Scope

- CaaS API server (`cortex/caas/server.py`)
- Authentication and authorization (grant tokens, OAuth, CSRF)
- Audit ledger integrity (hash chain, tamper detection)
- Input validation and injection prevention
- Rate limiting and DoS protection
- Webhook security (SSRF prevention, circuit breaker)
- Cryptographic operations (identity, signing, key rotation)
- Federation security (bundle signing, trust model)

### Out of Scope

- Vulnerabilities in third-party dependencies (report upstream)
- Denial of service via resource exhaustion without authentication
- Social engineering attacks
- Physical security
- Issues requiring local access to the server filesystem

## Security Documentation

For deployment hardening guidance, see:

- [Security Overview](docs/security.md) -- Architecture, threat model, and controls
- [Deployment Checklist](docs/security-checklist.md) -- Pre-production security checklist
- [Dependency Audit](docs/dependency-audit.md) -- Third-party dependency review
- [Penetration Test Plan](docs/pentest-plan.md) -- OWASP-aligned test procedures
