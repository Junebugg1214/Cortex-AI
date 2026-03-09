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

- **Critical:** Remote code execution, signature forgery, malicious graph import leading to arbitrary file access
- **High:** Privilege escalation in local key handling, disclosure bypass, unsafe deserialization
- **Medium:** Information disclosure (non-sensitive), path traversal in local workflows, denial of service via crafted inputs
- **Low:** Verbose error messages, hardening gaps, documentation mistakes

## Scope

### In Scope

- CLI commands and local file workflows
- Graph import, export, and parsing logic
- Cryptographic operations (identity, signing, key rotation)
- Disclosure policy evaluation
- Federation security (bundle signing, trust model)

### Out of Scope

- Vulnerabilities in third-party dependencies (report upstream)
- Denial of service via resource exhaustion on obviously unbounded local inputs
- Social engineering attacks
- Physical security
- Issues that require prior local access to the user's filesystem or shell
