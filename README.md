<h1 align="center">Cortex</h1>
<p align="center"><strong>Own your AI memory. Take it everywhere.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/cortex-identity/"><img src="https://img.shields.io/pypi/v/cortex-identity?color=blue&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/cortex-identity/"><img src="https://img.shields.io/pypi/pyversions/cortex-identity" alt="Python"></a>
  <a href="https://github.com/Junebugg1214/Cortex-AI/blob/main/LICENSE"><img src="https://img.shields.io/github/license/Junebugg1214/Cortex-AI" alt="License"></a>
  <a href="https://github.com/Junebugg1214/Cortex-AI/stargazers"><img src="https://img.shields.io/github/stars/Junebugg1214/Cortex-AI?style=social" alt="Stars"></a>
  <img src="https://img.shields.io/badge/tests-1%2C710%20passing-brightgreen" alt="Tests">
</p>

---

**Your ChatGPT knows you. Now Claude does too.**

Cortex extracts your context from ChatGPT, Claude, Gemini, Perplexity, and coding tools (Claude Code, Cursor, Copilot) — builds a portable knowledge graph you own — and pushes it to any platform or serves it over HTTP as an API. Cryptographically signed. Version controlled. Protocol-grade. Zero dependencies. Multiple storage backends (SQLite, PostgreSQL). SDKs for Python and TypeScript.

### Own your memory

<p align="center">
  <img src="assets/demo-own.gif" alt="Extract and query your AI memory" width="800">
</p>

### Share it how you want

<p align="center">
  <img src="assets/demo-share.gif" alt="Disclosure policies control what each platform sees" width="800">
</p>

### Serve it as an API

<p align="center">
  <img src="assets/demo-api.gif" alt="CaaS server with grant tokens and HTTP access" width="800">
</p>

## Quick Start

```bash
pip install cortex-identity

# Migrate ChatGPT → Claude in one command
cortex chatgpt-export.zip --to claude -o ./output

# See what it extracted
cortex stats output/context.json

# Visualize your knowledge graph
cortex viz output/context.json --output graph.html
```

## What Makes This Different

| | Cortex | Mem0 | Letta | ChatGPT Memory | Claude Memory |
|---|:-:|:-:|:-:|:-:|:-:|
| **You own it** | Yes | No | No | No | No |
| **Portable** | Yes | No | No | No | No |
| **Knowledge graph** | Yes | Partial | No | No | No |
| **API-ready** | Yes | No | No | No | No |
| **Cryptographic identity** | Yes | No | No | No | No |
| **Role-based access (RBAC)** | Yes | No | No | No | No |
| **OAuth 2.0 / OIDC** | Yes | No | No | No | No |
| **SDKs (Python + TypeScript)** | Yes | Partial | No | No | No |
| **Temporal tracking** | Yes | No | No | No | No |
| **Works offline** | Yes | No | No | No | No |
| **Zero dependencies** | Yes | No | No | N/A | N/A |

> Mem0, Letta, and built-in AI memories are **agent memory** — owned by the platform. Cortex is **your memory**, under **your control**.

## How It Works

```
Chat Exports (ChatGPT, Claude, Gemini, Perplexity)
  + Coding Sessions (Claude Code, Cursor, Copilot)
        |
   Extract ──→ Knowledge Graph ──→ Sign & Version ──┬──→ Push Anywhere
                                                     └──→ Serve via API (CaaS)
```

Nodes are entities, not category items. "Python" is ONE node with tags `[technical_expertise, domain_knowledge]` — not duplicated across categories. Edges capture typed relationships: `Python --applied_in--> Healthcare`.

## Installation

```bash
pip install cortex-identity              # Core (zero dependencies)
pip install cortex-identity[crypto]      # + Ed25519 signatures
pip install cortex-identity[fast]        # + 10x faster graph layout
pip install cortex-identity[postgres]    # + PostgreSQL storage backend
pip install cortex-identity[full]        # Everything
```

<details>
<summary><strong>Install from source</strong></summary>

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
pip install -e .
```

Requires Python 3.10+ (macOS, Linux, Windows). No external packages required for core functionality.

</details>

---

## Features

<details>
<summary><strong>Knowledge Graph Engine</strong></summary>

### Graph Foundation

Everything is nodes and edges. Nodes have tags (not fixed categories), confidence scores, temporal metadata, and extensible properties. The graph is backward compatible — v4 flat-category JSON converts losslessly.

```bash
cortex query context.json --node "Python"
cortex query context.json --neighbors "Python"
cortex stats context.json
```

### Smart Edges

Automatic relationship discovery:

- **Pattern rules** — `technical_expertise` + `active_priorities` = `used_in` edge
- **Co-occurrence** — entities appearing together in messages get linked (PMI for large datasets, frequency thresholds for small)
- **Centrality** — identifies your most important nodes (degree centrality, PageRank for 200+ nodes)
- **Graph-aware dedup** — merges near-duplicates using 70% text similarity + 30% neighbor overlap

### Query + Intelligence

```bash
cortex query context.json --category technical_expertise
cortex query context.json --strongest 10
cortex query context.json --isolated
cortex query context.json --path "Python" "Mayo Clinic"
cortex query context.json --components
cortex gaps context.json
cortex digest context.json --previous last_week.json
```

</details>

<details>
<summary><strong>UPAI Protocol (Cryptographic Identity)</strong></summary>

Full protocol specification: [`spec/upai-v1.0.md`](spec/upai-v1.0.md)

- **W3C `did:key` identity** — Ed25519 multicodec + base58btc. Interoperable with the decentralized identity ecosystem.
- **Cryptographic signing** — SHA-256 integrity (always). Ed25519 signatures (with `pynacl`). Proves the graph is yours and untampered.
- **Signed envelopes** — Three-part `header.payload.signature` format with replay protection (nonce, iat, exp, audience binding).
- **Signed grant tokens** — Scoped access tokens (`context:read`, `versions:read`) with Ed25519 signatures and expiration.
- **Key rotation** — Rotate to a new keypair with a verifiable revocation chain. Old keys get revocation proofs.
- **Selective disclosure** — Policies control what each platform sees. "Professional" shows job/skills. "Technical" shows your tech stack. "Minimal" shows almost nothing.
- **Version control** — Git-like commits for your identity. Log, diff, checkout, rollback.
- **Verifiable credentials** — Issue and verify W3C-style credentials bound to your DID.
- **Encrypted backup** — AES-256-GCM encrypted identity exports with key-derived encryption.
- **Service discovery** — `.well-known/upai-configuration` endpoint for automated client bootstrapping.
- **RBAC** — Role-based access control with 4 roles (owner, admin, editor, viewer) and 10 permission scopes.
- **JSON Schema validation** — 9 schemas for all data structures, stdlib-only validator.
- **Structured error codes** — UPAI-4xxx (client) and UPAI-5xxx (server) error registry.
- **Webhook signing** — HMAC-SHA256 payload signatures for event notifications.

```bash
cortex identity --init --name "Your Name"
cortex commit context.json -m "Added June ChatGPT export"
cortex log
cortex identity --show
cortex sync context.json --to claude --policy professional -o ./output
cortex rotate                                    # Rotate identity keys
```

**Built-in disclosure policies:**

| Policy | What's Shared | Min Confidence |
|--------|---------------|----------------|
| `full` | Everything | 0.0 |
| `professional` | Identity, work, skills, priorities | 0.6 |
| `technical` | Tech stack, domain knowledge, priorities | 0.5 |
| `minimal` | Identity, communication preferences only | 0.8 |

</details>

<details>
<summary><strong>Context-as-a-Service (CaaS) API</strong></summary>

Serve your context over HTTP so AI platforms can pull it directly. OpenAPI spec: [`spec/openapi.json`](spec/openapi.json)

```bash
# Start the CaaS server
cortex serve context.json --port 8421

# With PostgreSQL storage
cortex serve context.json --storage postgres --db-url "dbname=cortex"

# With SSE and Prometheus metrics
cortex serve context.json --enable-sse --enable-metrics

# With INI config file
cortex serve context.json --config deploy/cortex.ini

# Create a scoped access token for a platform
cortex grant --create --audience "Claude" --policy professional

# Revoke or list grants
cortex grant --list
cortex grant --revoke <grant_id>

# Manage custom disclosure policies
cortex policy --list
cortex policy --create --name "team" --include-tags technical_expertise domain_knowledge
```

**40+ API endpoints** across 12 groups:

| Group | Endpoints | Auth |
|-------|-----------|------|
| Discovery | `/.well-known/upai-configuration`, `/identity`, `/health` | None |
| Grants | `POST/GET/DELETE /grants` | Self-managed |
| Context | `/context`, `/context/compact`, `/context/nodes`, `/context/edges`, `/context/stats` | `context:read` |
| Graph Queries | `/context/path/<from>/<to>`, `POST /context/search`, `POST /context/batch` | `context:read` |
| CRUD | `POST/GET/PATCH/DELETE` on individual nodes and edges | `context:write` |
| Versions | `/versions`, `/versions/<id>`, `/versions/diff` | `versions:read` |
| Webhooks | `POST/GET/DELETE /webhooks` | Self-managed |
| Credentials | `POST/GET/DELETE /credentials`, `/credentials/<id>/verify` | `credentials:*` |
| Policies | `POST/GET/PATCH/DELETE /policies` | Owner |
| Audit | `/audit`, `/audit/verify` | Owner |
| SSE | `/events` (Server-Sent Events, `--enable-sse`) | `context:read` |
| Dashboard | `/dashboard` (SPA with OAuth login) | Session / OAuth |

**Auth flow:** Platform requests a signed grant token with `cortex grant` -> uses it as `Authorization: Bearer <token>` -> server verifies signature, expiry, and scope -> returns disclosure-filtered context.

</details>

<details>
<summary><strong>Storage Backends</strong></summary>

Cortex supports three storage backends, selectable via CLI flag:

| Backend | Flag | Use Case |
|---------|------|----------|
| JSON | `--storage json` (default) | Single-user, file-based, zero setup |
| SQLite | `--storage sqlite --db-path cortex.db` | Embedded SQL, concurrent reads, migrations |
| PostgreSQL | `--storage postgres --db-url "dbname=cortex"` | Production deployments, multi-instance |

```bash
# JSON (default — just works)
cortex serve context.json

# SQLite
cortex serve context.json --storage sqlite --db-path ./data/cortex.db

# PostgreSQL
cortex serve context.json --storage postgres --db-url "host=localhost dbname=cortex_prod user=cortex"
```

All backends share the same `StorageBackend` interface. SQLite and PostgreSQL include automatic schema migrations. PostgreSQL requires the optional `psycopg` dependency (`pip install cortex-identity[postgres]`).

</details>

<details>
<summary><strong>SDKs</strong></summary>

### Python SDK

Built-in Python client for the CaaS API:

```python
from cortex.sdk.client import CortexClient

client = CortexClient("http://localhost:8421", token="your-grant-token")
context = client.get_context()
nodes = client.list_nodes(limit=10)
stats = client.get_stats()
```

### TypeScript SDK

Zero-dependency TypeScript/JavaScript client (`@cortex-ai/sdk`):

```typescript
import { CortexClient } from '@cortex-ai/sdk';

const client = new CortexClient({
  baseUrl: 'http://localhost:8421',
  token: 'your-grant-token',
});

const context = await client.getContext();
const nodes = await client.listNodes({ limit: 10 });
const stats = await client.getStats();
```

- **Zero runtime dependencies** — native `fetch`, no axios/node-fetch
- **ESM + CJS dual build** — works in Node.js, Deno, Bun, and bundlers
- **Full TypeScript types** — all request/response types exported
- **33 tests** via `node:test`

Install: `npm install @cortex-ai/sdk`

</details>

<details>
<summary><strong>Security & Operations</strong></summary>

### Role-Based Access Control (RBAC)

4 roles with 10 permission scopes:

| Role | Permissions |
|------|-------------|
| **owner** | All scopes — full control |
| **admin** | Manage grants, webhooks, policies, credentials |
| **editor** | Read + write context and versions |
| **viewer** | Read-only context and versions |

### OAuth 2.0 / OIDC

```bash
cortex serve context.json \
  --oauth-provider google CLIENT_ID CLIENT_SECRET \
  --oauth-allowed-email you@example.com
```

Supports any OAuth 2.0 / OpenID Connect provider. Token exchange endpoint converts OAuth tokens into Cortex grant tokens.

### Rate Limiting

Token-bucket rate limiter per client IP. Configurable burst and sustained rates.

### Field-Level Encryption

AES-256-GCM encryption for sensitive node properties at rest. Key management via identity keychain.

### Audit Ledger

Hash-chained SHA-256 audit log. Every mutation is recorded with actor, timestamp, and cryptographic chain integrity. Tamper-evident — `GET /audit/verify` checks the full chain.

### CSRF / SSRF Protection

- CSRF tokens for dashboard session endpoints
- SSRF guards on webhook delivery (blocks private IP ranges)
- CORS configuration via `--allowed-origins`

### Prometheus Metrics

```bash
cortex serve context.json --enable-metrics
# GET /metrics → Prometheus-format counters
```

9 custom metrics: request latency histograms, webhook delivery counts, SSE connection gauges, storage operation counters, error rates, and more.

</details>

<details>
<summary><strong>Deployment</strong></summary>

Production deployment configs included in `deploy/`:

### Docker

```bash
docker build -t cortex .
docker run -p 8421:8421 -v cortex-data:/data cortex
```

### Docker Compose

```bash
docker compose up -d   # Cortex + PostgreSQL + Caddy
```

### systemd

```bash
sudo cp deploy/cortex.service /etc/systemd/system/
sudo systemctl enable --now cortex
```

### Reverse Proxy

Caddy and nginx configs included:

```bash
# Caddy (auto-TLS)
cp deploy/Caddyfile /etc/caddy/Caddyfile

# nginx
cp deploy/nginx.conf /etc/nginx/conf.d/cortex.conf
```

### INI Configuration

```ini
# deploy/cortex.ini
[server]
port = 8421
storage = postgres
db_url = host=localhost dbname=cortex_prod

[security]
allowed_origins = https://yourdomain.com
enable_sse = true
enable_metrics = true
```

```bash
cortex serve context.json --config deploy/cortex.ini
```

See [`docs/deployment.md`](docs/deployment.md) for the full deployment guide.

</details>

<details>
<summary><strong>Temporal Tracking & Contradictions</strong></summary>

Every extraction snapshots each node's state. Cortex tracks how your identity evolves, detects contradictions ("said X in January, not-X in March"), and computes drift scores across time windows.

```bash
cortex timeline context.json --format html
cortex contradictions context.json --severity 0.5
cortex drift context.json --compare previous.json
```

### Conflict Detection

```
Input: "I use Python daily" + "I don't use Python anymore"
Result: negation_conflict detected, resolution: prefer_negation (more recent)
```

### Typed Relationships

```
Input: "We partner with Mayo Clinic. Dr. Smith is my mentor."
Result: Mayo Clinic (partner), Dr. Smith (mentor)
```

Supported types: `partner`, `mentor`, `advisor`, `investor`, `client`, `competitor`

</details>

<details>
<summary><strong>Visualization & Dashboard</strong></summary>

```bash
cortex viz context.json --output graph.html          # Interactive HTML
cortex viz context.json --output graph.svg --format svg  # Static SVG
cortex dashboard context.json --port 8420            # Web dashboard
cortex watch ~/exports/ --graph context.json         # Auto-extract
cortex sync-schedule --config sync_config.json       # Scheduled sync
```

The CaaS server includes a built-in admin dashboard at `/dashboard` with session-based authentication and optional OAuth login.

</details>

<details>
<summary><strong>Coding Tool Extraction</strong></summary>

Extract identity from what you *actually do*, not just what you say. Coding sessions reveal your real tech stack, tools, and workflow through behavior:

```bash
cortex extract-coding --discover -o coding_context.json
cortex extract-coding --discover --project chatbot-memory
cortex extract-coding --discover --merge context.json -o context.json
cortex extract-coding --discover --enrich --stats
```

| Signal | How | Example |
|--------|-----|---------|
| Languages | File extensions | Editing `.py` files -> Python |
| Frameworks | Config files | `package.json` -> Node.js |
| CLI tools | Bash commands | Running `pytest` -> Pytest |
| Projects | Working directory | `/home/user/myapp` -> myapp |
| Patterns | Tool sequence | Uses plan mode before coding |

**Project enrichment** (`--enrich`): Reads README, package manifests, and LICENSE files to extract project metadata. Detects CI/CD and Docker presence.

Currently supports **Claude Code** (JSONL transcripts). Cursor and Copilot parsers planned.

</details>

<details>
<summary><strong>Auto-Inject & Cross-Platform Context</strong></summary>

### Auto-Inject into Claude Code

Every new session automatically gets your Cortex identity injected:

```bash
cortex context-hook install context.json
cortex context-hook test
cortex context-export context.json --policy technical
```

### Cross-Platform Context Writer

Write persistent Cortex identity to every AI coding tool:

```bash
cortex context-write graph.json --platforms all --project ~/myproject
cortex context-write graph.json --platforms cursor copilot windsurf
cortex context-write graph.json --platforms all --dry-run
cortex context-write graph.json --platforms all --watch
```

| Platform | Config File | Scope |
|----------|------------|-------|
| Claude Code | `~/.claude/MEMORY.md` | Global |
| Claude Code (project) | `{project}/.claude/MEMORY.md` | Project |
| Cursor | `{project}/.cursor/rules/cortex.mdc` | Project |
| GitHub Copilot | `{project}/.github/copilot-instructions.md` | Project |
| Windsurf | `{project}/.windsurfrules` | Project |
| Gemini CLI | `{project}/GEMINI.md` | Project |

Uses `<!-- CORTEX:START -->` / `<!-- CORTEX:END -->` markers — your hand-written rules are never overwritten.

</details>

<details>
<summary><strong>Continuous Extraction</strong></summary>

Watch Claude Code sessions in real-time. Auto-extract behavioral signals as you code:

```bash
cortex extract-coding --watch -o coding_context.json
cortex extract-coding --watch -o ctx.json --context-refresh claude-code cursor copilot
cortex extract-coding --watch --project chatbot-memory -o ctx.json
cortex extract-coding --watch --interval 15 --settle 10 -o ctx.json
```

Polls for session changes, debounces active writes, and incrementally merges nodes.

</details>

<details>
<summary><strong>PII Redaction</strong></summary>

Strip sensitive data before extraction:

```bash
cortex chatgpt-export.zip --to claude --redact
cortex chatgpt-export.zip --to claude --redact --redact-patterns custom.json
```

Redacts: emails, phones, SSNs, credit cards, API keys, IP addresses, street addresses.

</details>

---

<details>
<summary><strong>Supported Platforms</strong></summary>

### Input (Extract From)

| Platform | File Type | Auto-Detected |
|----------|-----------|---------------|
| ChatGPT | `.zip` with `conversations.json` | Yes |
| Claude | `.json` with messages array | Yes |
| Claude Memories | `.json` array with `text` field | Yes |
| Gemini / AI Studio | `.json` with conversations/turns | Yes |
| Perplexity | `.json` with threads | Yes |
| API Logs | `.json` with requests array | Yes |
| JSONL | `.jsonl` (one message per line) | Yes |
| Claude Code | `.jsonl` session transcripts | Yes |
| Plain Text | `.txt`, `.md` | Yes |

### Output (Export To)

| Format | Output | Use Case |
|--------|--------|----------|
| Claude Preferences | `claude_preferences.txt` | Settings > Profile |
| Claude Memories | `claude_memories.json` | memory_user_edits |
| System Prompt | `system_prompt.txt` | Any LLM API |
| Notion Page | `notion_page.md` | Notion import |
| Notion Database | `notion_database.json` | Notion DB rows |
| Google Docs | `google_docs.html` | Google Docs paste |
| Summary | `summary.md` | Human overview |
| Full JSON | `full_export.json` | Lossless backup |

### Extraction Categories

Cortex extracts entities into 17 tag categories:

| Category | Examples |
|----------|----------|
| Identity | Name, credentials (MD, PhD) |
| Professional Context | Role, title, company |
| Business Context | Company, products, metrics |
| Active Priorities | Current projects, goals |
| Relationships | Partners, clients, collaborators |
| Technical Expertise | Languages, frameworks, tools |
| Domain Knowledge | Healthcare, finance, AI/ML |
| Market Context | Competitors, industry trends |
| Metrics | Revenue, users, timelines |
| Constraints | Budget, timeline, team size |
| Values | Principles, beliefs |
| Negations | What you explicitly avoid |
| User Preferences | Style and tool preferences |
| Communication Preferences | Response style preferences |
| Correction History | Self-corrections |
| Mentions | Catch-all for other entities |

</details>

<details>
<summary><strong>Full CLI Reference (28 commands)</strong></summary>

### Extract & Import

```bash
cortex <export> --to <platform> -o ./output    # One-step migrate
cortex extract <export> -o context.json         # Extract only
cortex import context.json --to <platform>      # Import only
cortex extract new.json --merge old.json -o merged.json  # Merge contexts
```

### Query & Intelligence

```bash
cortex query <graph> --node <label>             # Find node
cortex query <graph> --neighbors <label>        # Find neighbors
cortex query <graph> --category <tag>           # Filter by tag
cortex query <graph> --path <from> <to>         # Shortest path
cortex query <graph> --strongest <n>            # Top N nodes
cortex query <graph> --weakest <n>              # Bottom N nodes
cortex query <graph> --isolated                 # Unconnected nodes
cortex query <graph> --components               # Connected clusters
cortex gaps <graph>                             # Gap analysis
cortex digest <graph> --previous <old>          # Weekly digest
cortex stats <graph>                            # Graph statistics
```

### Identity & Sync

```bash
cortex identity --init --name <name>             # Create identity
cortex commit <graph> -m <message>               # Version commit
cortex log                                       # Version history
cortex identity --show                           # Show identity
cortex sync <graph> --to <platform> --policy <name>  # Push to platform
```

### Visualization & Flywheel

```bash
cortex viz <graph> --output graph.html          # Interactive HTML
cortex viz <graph> --output graph.svg --format svg  # Static SVG
cortex dashboard <graph> --port 8420            # Web dashboard
cortex watch <dir> --graph <graph>              # Auto-extract
cortex sync-schedule --config <config.json>     # Scheduled sync
```

### Coding Tool Extraction

```bash
cortex extract-coding <session.jsonl>           # From specific file
cortex extract-coding --discover                # Auto-find sessions
cortex extract-coding --discover -p <project>   # Filter by project
cortex extract-coding --discover -m <context>   # Merge with existing
cortex extract-coding --discover --stats        # Show session stats
cortex extract-coding --discover --enrich       # Enrich with project files
cortex extract-coding --watch -o ctx.json       # Watch mode (continuous)
cortex extract-coding --watch --context-refresh claude-code cursor  # Watch + auto-refresh
```

### Context Hook (Auto-Inject)

```bash
cortex context-hook install <graph> --policy technical  # Install hook
cortex context-hook uninstall                   # Remove hook
cortex context-hook test                        # Preview injection
cortex context-hook status                      # Check status
cortex context-export <graph> --policy technical  # One-shot export
```

### Cross-Platform Context Writer

```bash
cortex context-write <graph> --platforms all --project <dir>  # All platforms
cortex context-write <graph> --platforms cursor copilot       # Specific platforms
cortex context-write <graph> --platforms all --dry-run        # Preview
cortex context-write <graph> --platforms all --watch          # Auto-refresh
cortex context-write <graph> --platforms all --policy professional  # Policy override
```

### Context-as-a-Service (CaaS)

```bash
cortex serve <graph> --port 8421                 # Start CaaS server
cortex serve <graph> --storage postgres --db-url "dbname=cortex"  # PostgreSQL backend
cortex serve <graph> --config deploy/cortex.ini  # INI config file
cortex serve <graph> --enable-sse --enable-metrics  # SSE + Prometheus
cortex grant --create --audience <name>          # Create access token
cortex grant --list                              # List grants
cortex grant --revoke <grant_id>                 # Revoke grant
cortex policy --list                             # List disclosure policies
cortex policy --create --name <name> --include-tags <tags>  # Create custom policy
cortex rotate                                    # Rotate identity keys
```

### Temporal Analysis

```bash
cortex timeline <graph> --format html           # Timeline view
cortex contradictions <graph> --severity 0.5    # Find conflicts
cortex drift <graph> --compare previous.json    # Identity drift
```

</details>

<details>
<summary><strong>Architecture</strong></summary>

```
cortex-identity/                    # pip install cortex-identity
├── pyproject.toml                  # Package metadata + entry points
├── Dockerfile                     # Container build
├── docker-compose.yml             # Multi-service deployment
├── spec/
│   ├── upai-v1.0.md            # UPAI protocol specification (RFC-style)
│   └── openapi.json            # OpenAPI 3.1 CaaS API specification
├── deploy/
│   ├── cortex.ini              # INI configuration template
│   ├── cortex.service          # systemd unit file
│   ├── Caddyfile               # Caddy reverse proxy (auto-TLS)
│   ├── nginx.conf              # nginx reverse proxy
│   └── .env.example            # Environment variable template
├── docs/
│   ├── architecture.md         # System architecture
│   ├── deployment.md           # Deployment guide
│   ├── user-guide.md           # User documentation
│   ├── tutorial.md             # Getting started
│   └── overview.md             # Project overview
├── sdk/
│   └── typescript/             # @cortex-ai/sdk (TypeScript)
│       ├── src/
│       │   ├── client.ts       # CaaS API client
│       │   ├── types.ts        # Request/response types
│       │   ├── errors.ts       # Error classes
│       │   └── index.ts        # Public exports
│       └── package.json        # Zero runtime deps, ESM+CJS
├── cortex/                        # 75 source files
│   ├── cli.py                  # CLI entry point (28 subcommands)
│   ├── extract_memory.py       # Extraction engine (~1400 LOC)
│   ├── import_memory.py        # Import/export engine (~1000 LOC)
│   ├── graph.py                # Node, Edge, CortexGraph (schema 6.0)
│   ├── compat.py               # v4 <-> v5 conversion
│   ├── temporal.py             # Snapshots, drift scoring
│   ├── contradictions.py       # Contradiction detection
│   ├── timeline.py             # Timeline views
│   ├── upai/                   # Universal Personal AI Protocol (14 files)
│   │   ├── identity.py         # did:key identity, Ed25519/HMAC, SignedEnvelope
│   │   ├── disclosure.py       # Selective disclosure policies
│   │   ├── versioning.py       # Git-like version control
│   │   ├── schemas.py          # JSON Schema validation (stdlib-only)
│   │   ├── tokens.py           # Signed grant tokens (Ed25519)
│   │   ├── keychain.py         # Key rotation & revocation chain
│   │   ├── errors.py           # Structured error codes (UPAI-4xxx/5xxx)
│   │   ├── pagination.py       # Cursor-based pagination
│   │   ├── webhooks.py         # HMAC-SHA256 webhook signing
│   │   ├── credentials.py      # Verifiable credentials (W3C-style)
│   │   ├── discovery.py        # Service discovery endpoint
│   │   ├── backup.py           # AES-256-GCM encrypted backup
│   │   └── rbac.py             # Role-based access control
│   ├── caas/                   # Context-as-a-Service (25 files)
│   │   ├── server.py           # HTTP API server (40+ endpoints)
│   │   ├── storage.py          # StorageBackend interface
│   │   ├── sqlite_store.py     # SQLite backend + migrations
│   │   ├── postgres_store.py   # PostgreSQL backend
│   │   ├── config.py           # INI file configuration
│   │   ├── oauth.py            # OAuth 2.0 / OIDC integration
│   │   ├── sse.py              # Server-Sent Events
│   │   ├── event_buffer.py     # SSE replay (Last-Event-ID)
│   │   ├── rate_limit.py       # Token-bucket rate limiter
│   │   ├── webhook_worker.py   # Async webhook delivery
│   │   ├── circuit_breaker.py  # Webhook circuit breaker
│   │   ├── dead_letter.py      # Dead-letter queue
│   │   ├── audit_ledger.py     # Hash-chained audit log
│   │   ├── sqlite_audit_ledger.py
│   │   ├── postgres_audit_ledger.py
│   │   ├── caching.py          # HTTP caching (ETags, Cache-Control)
│   │   ├── correlation.py      # Request correlation IDs
│   │   ├── encryption.py       # Field-level AES-256-GCM
│   │   ├── metrics.py          # Prometheus metrics
│   │   ├── instrumentation.py  # Observability hooks
│   │   ├── logging_config.py   # Structured logging
│   │   ├── migrations.py       # Schema migrations
│   │   ├── shutdown.py         # Graceful shutdown
│   │   └── dashboard/          # Admin dashboard (auth + static)
│   ├── sdk/                    # Python SDK client
│   │   ├── client.py           # CaaS API client
│   │   └── exceptions.py       # SDK error types
│   ├── adapters.py             # Claude/SystemPrompt/Notion/GDocs adapters
│   ├── edge_extraction.py      # Pattern-based + proximity edge discovery
│   ├── cooccurrence.py         # PMI / frequency co-occurrence
│   ├── dedup.py                # Graph-aware deduplication
│   ├── centrality.py           # Degree centrality + PageRank
│   ├── query.py                # QueryEngine + graph algorithms
│   ├── intelligence.py         # Gap analysis + weekly digest
│   ├── coding.py               # Coding session behavioral extraction
│   ├── hooks.py                # Auto-inject context into Claude Code
│   ├── context.py              # Cross-platform context writer (6 platforms)
│   ├── continuous.py           # Real-time session watcher
│   ├── _hook.py                # cortex-hook entry point
│   ├── __main__.py             # python -m cortex support
│   ├── viz/                    # Visualization (renderer + layout)
│   ├── dashboard/              # Local web dashboard
│   └── sync/                   # File watcher + scheduled sync
├── migrate.py                  # Backward-compat stub → cortex.cli
├── cortex-hook.py              # Backward-compat stub → cortex._hook
└── tests/                      # 1,710 tests across 62 files
```

</details>

<details>
<summary><strong>Version History</strong></summary>

| Version | Milestone |
|---------|-----------|
| v1.2.0 | **Production Hardening + SDKs + PostgreSQL** — RBAC (4 roles, 10 scopes), hash-chained audit ledger, HTTP caching (ETags), webhook resilience (circuit breaker, dead-letter queue), SSE with replay, OAuth 2.0/OIDC, field-level encryption, rate limiting, CSRF/SSRF protection, structured logging, graceful shutdown, verifiable credentials, encrypted backup, service discovery, custom disclosure policies, graph CRUD API, admin dashboard, Docker/systemd/Caddy/nginx deployment, INI config, SQLite storage backend, PostgreSQL storage backend, Python SDK, TypeScript SDK (`@cortex-ai/sdk`), Prometheus metrics (9 custom metrics). 28 CLI commands. 1,710 tests. |
| v1.1.0 | **UPAI Open Standard + CaaS API** — W3C `did:key` identity, signed envelopes with replay protection, signed grant tokens, key rotation chain, Context-as-a-Service HTTP API (18 endpoints), JSON Schema validation, structured error codes, cursor-based pagination, webhook signing, OpenAPI 3.1 spec, RFC-style protocol spec. 27 CLI commands. 796 tests. |
| v1.0.0 | **First public release** — 24 CLI commands, knowledge graph, UPAI protocol, temporal tracking, coding extraction, cross-platform context, continuous extraction, visualization, dashboard. 618 tests. Zero required dependencies. |

<details>
<summary>Pre-release development history</summary>

| Internal | Milestone |
|----------|-----------|
| v6.4 (dev) | pip packaging, continuous extraction, production hardening |
| v6.3 (dev) | Cross-platform context writer |
| v6.2 (dev) | Auto-inject context |
| v6.1 (dev) | Coding tool extraction |
| v6.0 (dev) | Visualization, dashboard, file monitor, sync scheduler |
| v5.4 (dev) | Query engine, gap analysis, weekly digest |
| v5.3 (dev) | Smart edge extraction, co-occurrence, centrality, dedup |
| v5.2 (dev) | UPAI Protocol — cryptographic signing, selective disclosure, version control |
| v5.1 (dev) | Temporal snapshots, contradiction engine, drift scoring |
| v5.0 (dev) | Graph foundation — category-agnostic nodes, edges |
| v4.x (dev) | PII redaction, typed relationships, Notion/Google Docs, semantic dedup |

</details>

</details>

---

## License

MIT — See [LICENSE](LICENSE)

## Author

Created by [@Junebugg1214](https://github.com/Junebugg1214)
