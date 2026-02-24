<h1 align="center">Cortex</h1>
<p align="center"><strong>A personal memory system for AI. Own it. Take it everywhere.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/cortex-identity/"><img src="https://img.shields.io/pypi/v/cortex-identity?color=blue&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/cortex-identity/"><img src="https://img.shields.io/pypi/pyversions/cortex-identity" alt="Python"></a>
  <a href="https://github.com/Junebugg1214/Cortex-AI/blob/main/LICENSE"><img src="https://img.shields.io/github/license/Junebugg1214/Cortex-AI" alt="License"></a>
  <a href="https://github.com/Junebugg1214/Cortex-AI/stargazers"><img src="https://img.shields.io/github/stars/Junebugg1214/Cortex-AI?style=social" alt="Stars"></a>
  <a href="https://www.npmjs.com/package/@cortex_ai/sdk"><img src="https://img.shields.io/npm/v/@cortex_ai/sdk?color=cb3837&label=npm" alt="npm"></a>
  <img src="https://img.shields.io/badge/tests-2%2C138%20passing-brightgreen" alt="Tests">
</p>

---

## The Problem

Every time you talk to ChatGPT, Claude, or any AI assistant, you start from scratch. The AI doesn't know who you are, what you do, what tools you use, or what you care about. You repeat yourself constantly. Your history is scattered across platforms you don't control.

## What Cortex Does

Cortex watches your conversations, reads your resumes, pulls from your LinkedIn and GitHub, and builds a **knowledge graph** — a structured map of everything about you: your skills, your job history, your projects, the technologies you use, your preferences, your goals.

Then it makes that context available to any AI tool you use, so they all just *know* you.

### How it works

1. **You feed it data** — Drop in your ChatGPT exports, upload your resume, connect your GitHub, import your LinkedIn. It reads everything and extracts the important stuff automatically.

2. **It builds a map of you** — Not just a list of facts, but a connected graph. "You know Python" connects to "You work at Company X" connects to "You're building a machine learning project." It tracks confidence levels, detects contradictions, and updates over time.

3. **It shares your context with AI tools** — Generate an API key, pick what you want to share (everything, just professional stuff, just technical skills), and give that URL to any AI assistant. Now Claude, Cursor, Copilot, or your custom chatbot knows who you are without you explaining.

```
Chat Exports (ChatGPT, Claude, Gemini, Perplexity)
  + Resumes (PDF, DOCX) + LinkedIn + GitHub
        |
   Extract --> Knowledge Graph --> Sign & Version --+--> Push to any AI tool
                                                    +--> Serve via API
                                                    +--> Web UI (explore & share)
```

Everything runs on your machine. No cloud service has your data. You own your identity, you control who sees what.

---

## Use Cases

### Make every AI conversation smarter from the start
Instead of telling Claude "I'm a backend engineer who uses Python and Kubernetes and works at Acme Corp" every session, it already knows. Your coding assistant gives you answers in your stack. Your writing assistant matches your style.

### Feed your resume to AI recruiters and agents
Upload your PDF resume, and Cortex extracts your skills, companies, roles, and education into structured data. Generate a shareable API key and any recruiting bot or career tool can pull your professional profile in a machine-readable format.

### Keep coding assistants in sync
Use Cursor at work and Claude Code at home? Cortex writes your context into all of them simultaneously — Claude Code's MEMORY.md, Cursor's rules, Copilot's instructions, Windsurf, Gemini CLI. One source of truth, everywhere.

### Team knowledge sharing with access control
Share your "technical" profile (just skills and projects, no personal info) with a junior dev's AI assistant so it gives advice consistent with your team's stack. Disclosure policies control exactly what gets exposed.

### Build AI agents that know their users
Building a chatbot or agent? Instead of asking users 20 onboarding questions, give them a Cortex memory URL. Your agent calls `GET /api/memory/{key}` and instantly has structured context — expertise level, preferences, domain knowledge — in whatever format you need (JSON, XML, markdown).

### Track how your knowledge evolves
Cortex versions your graph like git versions code. Diff two snapshots, see what skills you picked up last month, detect when your priorities shifted, get a weekly digest of how your profile is changing.

### Personal knowledge base from chat history
You've had thousands of AI conversations across ChatGPT, Claude, and Gemini. Drop all those exports into Cortex and it extracts every project, tool, technique, and preference you've ever mentioned — things you've forgotten you know.

### Self-host your own AI identity
No cloud service required. You own your DID (decentralized identifier), you sign your own credentials, you control who sees what. Portable and private.

---

## Quick Start

```bash
pip install cortex-identity

# Extract your ChatGPT history into a knowledge graph
cortex chatgpt-export.zip --to claude -o ./output

# See what it found
cortex stats output/context.json

# Visualize it
cortex viz output/context.json --output graph.html

# Serve it as an API
cortex serve output/context.json --enable-webapp --port 8421
# Open http://localhost:8421/app to upload, explore, and share
```

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

## What Makes This Different

| | Cortex | Mem0 | Letta | ChatGPT Memory | Claude Memory |
|---|:-:|:-:|:-:|:-:|:-:|
| **You own it** | Yes | No | No | No | No |
| **Portable** | Yes | No | No | No | No |
| **Knowledge graph** | Yes | Partial | No | No | No |
| **API-ready** | Yes | No | No | No | No |
| **Cryptographic identity** | Yes | No | No | No | No |
| **Web UI** | Yes | No | No | No | No |
| **Shareable memory API** | Yes | No | No | No | No |
| **Resume / LinkedIn / GitHub import** | Yes | No | No | No | No |
| **Role-based access (RBAC)** | Yes | No | No | No | No |
| **SDKs (Python + TypeScript)** | Yes | Partial | No | No | No |
| **Graph query language** | Yes | No | No | No | No |
| **Semantic search** | Yes | No | No | No | No |
| **Plugin system** | Yes | No | No | No | No |
| **Cross-instance federation** | Yes | No | No | No | No |
| **Works offline** | Yes | No | No | No | No |
| **Zero dependencies** | Yes | No | No | N/A | N/A |

> Mem0, Letta, and built-in AI memories are **agent memory** — owned by the platform. Cortex is **your memory**, under **your control**.

---

## Features

### Data Import

Drop files into the web UI or use the CLI. Cortex auto-detects the format and extracts structured facts.

| Source | How | What You Get |
|--------|-----|-------------|
| **ChatGPT** | Upload `.zip` export | Skills, projects, preferences, relationships from all your conversations |
| **Claude** | Upload `.json` export | Same — full extraction across all message formats |
| **Gemini / Perplexity** | Upload `.json` export | Auto-detected format, same extraction pipeline |
| **PDF Resume** | Upload or drag-drop | Identity, roles, companies, skills, education — structured and tagged |
| **DOCX Resume** | Upload or drag-drop | Same as PDF, parsed from Word XML (no dependencies) |
| **LinkedIn Data Export** | Upload `.zip` from Settings > Get a copy of your data | Profile, positions, skills, education, languages, certifications with relationship edges |
| **LinkedIn URL** | Paste profile URL | Limited OG meta data (LinkedIn blocks scraping) — data export recommended |
| **GitHub Repo** | Paste repo URL + optional token | Languages (with %), topics, stars, forks, README content |
| **Claude Code** | Auto-discovered `.jsonl` sessions | Technologies, tools, commands, projects from actual coding behavior |
| **Plain Text** | Upload `.txt` or `.md` | Single-pass extraction of whatever's there |

### Shareable Memory API

Generate API keys so external chatbots, agents, and coding tools can access your memory over HTTP.

```bash
# From the web UI: click "Generate API Key", pick a policy and format
# Or via API:
curl -X POST localhost:8421/api/keys \
  -H "Cookie: cortex_app_session=..." \
  -H "Content-Type: application/json" \
  -d '{"label": "My Claude context", "policy": "professional", "format": "claude_xml"}'

# Anyone with the key can fetch your memory (no auth needed):
curl localhost:8421/api/memory/cmk_a1b2c3d4_e5f6...
```

| Policy | What's Shared |
|--------|--------------|
| `full` | Everything in your graph |
| `professional` | Identity, work history, skills, priorities |
| `technical` | Tech stack, domain knowledge, active projects |
| `minimal` | Just your name and communication preferences |
| `custom` | You pick exactly which tags to include |

| Format | Best For |
|--------|---------|
| `json` | Programmatic access, SDKs, custom integrations |
| `claude_xml` | Claude system prompts (`<user-context>` tags) |
| `system_prompt` | Any LLM's system prompt (plain text) |
| `markdown` | Documentation, Notion, human-readable |

### Knowledge Graph Engine

Everything is nodes and edges. Nodes have tags (not rigid categories), confidence scores, temporal metadata, and properties.

- **16+ extraction methods** — identity, roles, companies, projects, skills, domains, relationships, values, priorities, metrics, negations, preferences, constraints, corrections, temporal context
- **Smart edges** — pattern rules, co-occurrence (PMI), centrality (PageRank), graph-aware dedup
- **Semantic search** — TF-IDF ranked search across all node fields (stdlib-only)
- **Query language** — `FIND tag=technical_expertise confidence>=0.8`, `NEIGHBORS "Python"`, `PATH "Python" TO "Healthcare"`, `SEARCH "web development"`
- **Intelligence** — gap analysis (5 detectors), weekly digest, contradiction detection (4 types), temporal drift scoring
- **17 tag categories** — identity, professional_context, technical_expertise, domain_knowledge, active_priorities, relationships, business_context, metrics, constraints, values, negations, education, and more

### Web UI

Start the server with `--enable-webapp` and open `http://localhost:8421/app`.

- **Upload page** — Drag-and-drop files (JSON, PDF, DOCX, zip), GitHub and LinkedIn URL import cards, API key management with policy/format configuration
- **My Memory page** — Interactive canvas graph with force-directed layout, zoom/pan, click-to-select, tag-colored nodes, search and filters
- **Share page** — Export to Claude, Notion, Google Docs, or system prompt format with privacy level selection and live preview

### Admin Dashboard

Available at `/dashboard` with session-based auth (password derived from your identity key).

- **Overview** — Stats, tag distribution, audit log
- **Graph Explorer** — Interactive canvas with policy filter
- **Grants** — Create/revoke access tokens with scope checkboxes and TTL
- **Versions** — Timeline + side-by-side diff
- **Settings** — Server config, OAuth, webhooks, policies, graph export

### UPAI Protocol (Cryptographic Identity)

Full spec: [`spec/upai-v1.0.md`](spec/upai-v1.0.md)

- **W3C DID identity** (`did:cortex:`) with Ed25519 signing
- **Grant tokens** — JWT-like, Ed25519-signed, 11 scopes, expiration
- **RBAC** — 5 roles (owner/admin/editor/reader/subscriber) mapped to scope subsets
- **Key rotation** — Multi-key management with revocation chain and grace periods
- **Disclosure policies** — 4 builtin + custom tag-based filtering
- **Verifiable credentials** — W3C VC 1.1 issuance and verification
- **Version control** — Git-like commits, diff, revert for your identity graph
- **Encrypted backup** — PBKDF2 + XOR cipher + HMAC integrity, 6 recovery codes
- **Service discovery** — `.well-known/upai-configuration`

```bash
cortex identity --init --name "Your Name"
cortex commit context.json -m "Added June ChatGPT export"
cortex log
cortex sync context.json --to claude --policy professional -o ./output
```

### Context-as-a-Service (CaaS) API

50+ REST endpoints. OpenAPI spec: [`spec/openapi.json`](spec/openapi.json). Interactive docs at `/docs`.

```bash
cortex serve context.json --port 8421 --enable-webapp --enable-sse --enable-metrics
```

| Group | Endpoints |
|-------|-----------|
| Discovery | `/.well-known/upai-configuration`, `/identity`, `/health`, `/docs` |
| Context | `/context`, `/context/compact`, `/context/nodes`, `/context/edges`, `/context/stats`, `/context/search`, `/context/query` |
| Grants | `POST/GET/DELETE /grants` |
| Versions | `/versions`, `/versions/<id>`, `/versions/diff` |
| Webhooks | `POST/GET/DELETE /webhooks` |
| Credentials | `POST/GET/DELETE /credentials` |
| Policies | `POST/GET/PATCH/DELETE /policies` |
| Audit | `/audit`, `/audit/verify` |
| Import | `POST /api/upload`, `POST /api/import/github`, `POST /api/import/linkedin` |
| Memory API | `POST/GET /api/keys`, `DELETE /api/keys/{id}`, `GET /api/memory/{key}` (public) |
| Federation | `/federation/export`, `/federation/import`, `/federation/peers` |
| Events | `/events` (SSE with Last-Event-ID replay) |
| Metrics | `/metrics` (Prometheus format, 17 metrics) |
| Web UI | `/app` (Upload, Memory, Share) |
| Dashboard | `/dashboard` (Overview, Graph, Grants, Versions, Settings) |

### Cross-Platform Context Writer

Write your Cortex identity into every AI coding tool simultaneously:

```bash
cortex context-write graph.json --platforms all --project ~/myproject
```

| Platform | Config File |
|----------|------------|
| Claude Code | `~/.claude/MEMORY.md` (global) |
| Claude Code | `{project}/.claude/MEMORY.md` (per-project) |
| Cursor | `{project}/.cursor/rules/cortex.mdc` |
| GitHub Copilot | `{project}/.github/copilot-instructions.md` |
| Windsurf | `{project}/.windsurfrules` |
| Gemini CLI | `{project}/GEMINI.md` |

Uses `<!-- CORTEX:START -->` / `<!-- CORTEX:END -->` markers — your hand-written rules are never overwritten.

### SDKs

**Python** (stdlib-only, zero dependencies):

```python
from cortex.sdk.client import CortexClient

client = CortexClient("http://localhost:8421", token="your-grant-token")
context = client.get_context()
nodes = client.list_nodes(limit=10)
```

**TypeScript** (zero runtime dependencies, `@cortex_ai/sdk`):

```typescript
import { CortexClient } from '@cortex_ai/sdk';

const client = new CortexClient({ baseUrl: 'http://localhost:8421', token: 'your-grant-token' });
const context = await client.getContext();
```

Install: `npm install @cortex_ai/sdk` — ESM + CJS dual build, full TypeScript types.

### Storage Backends

| Backend | Flag | Use Case |
|---------|------|----------|
| JSON | `--storage json` (default) | Single-user, file-based, zero setup |
| SQLite | `--storage sqlite --db-path cortex.db` | Embedded SQL, concurrent reads, migrations |
| PostgreSQL | `--storage postgres --db-url "dbname=cortex"` | Production deployments, multi-instance |

### Security & Operations

- **Rate limiting** — Sliding-window per-IP (default 60 req/60s)
- **OAuth 2.0 / OIDC** — Google and GitHub providers with PKCE
- **Webhook delivery** — Background worker with exponential backoff, circuit breaker, dead-letter queue
- **Audit ledger** — Hash-chained SHA-256 (tamper-evident)
- **HTTP caching** — ETags + Cache-Control + 304 Not Modified
- **Field encryption** — PBKDF2 + XOR + HMAC at rest
- **CSRF / SSRF protection** — Stateless HMAC tokens; DNS + IP range blocking
- **Distributed tracing** — W3C Trace Context spans with OTLP export
- **Prometheus metrics** — 17 metrics on `/metrics` (stdlib-only)
- **Plugin system** — 12 hooks for extending server behavior

### Deployment

Production configs included in `deploy/`:

```bash
# Docker
docker build -t cortex . && docker run -p 8421:8421 cortex

# Kubernetes (Helm)
helm install cortex deploy/helm/cortex --set storage.backend=postgres

# AWS (Terraform — ECS Fargate + ALB)
cd deploy/terraform/aws && terraform apply

# GCP (Terraform — Cloud Run)
cd deploy/terraform/gcp && terraform apply

# systemd
sudo cp deploy/cortex.service /etc/systemd/system/ && sudo systemctl enable --now cortex
```

Also includes: Caddy and nginx reverse proxy configs, Grafana dashboards (3 JSON), Locust load testing, INI config template, `.env.example`.

---

## CLI Reference

```bash
# Extract & Import
cortex <export> --to <platform> -o ./output      # One-step migrate
cortex extract <export> -o context.json           # Extract only
cortex import context.json --to <platform>        # Import only

# Query & Intelligence
cortex stats context.json                         # Graph statistics
cortex search context.json "machine learning"     # Semantic search
cortex query context.json --neighbors "Python"    # Graph traversal
cortex gaps context.json                          # Gap analysis
cortex digest context.json --previous old.json    # Weekly digest

# Identity & Versioning
cortex identity --init --name "Your Name"         # Create identity
cortex commit context.json -m "message"           # Version commit
cortex log                                        # Version history
cortex diff context.json --compare old.json       # Diff two versions

# Server
cortex serve context.json --enable-webapp         # Start with web UI
cortex grant --create --audience "Claude"          # Create access token
cortex policy --list                              # List disclosure policies

# Coding Tools
cortex extract-coding --discover -o coding.json   # Extract from Claude Code sessions
cortex context-write graph.json --platforms all    # Write to all AI tools
cortex context-hook install graph.json            # Auto-inject into Claude Code

# Visualization
cortex viz context.json --output graph.html       # Interactive HTML graph
cortex timeline context.json --format html        # Chronological timeline
```

30+ subcommands total. Run `cortex --help` for the full list, or `cortex completion --shell bash` for shell autocomplete.

---

## Architecture

```
cortex/
├── cli.py                  # 30+ CLI subcommands
├── extract_memory.py       # 16+ extraction methods (~1400 LOC)
├── import_memory.py        # 7 export formats (~1000 LOC)
├── graph.py                # Node, Edge, CortexGraph (schema 6.0)
├── upai/                   # Cryptographic identity protocol (14 modules)
├── caas/                   # HTTP API server (25+ modules)
│   ├── server.py           # 50+ REST endpoints
│   ├── importers.py        # PDF, DOCX, LinkedIn, GitHub import
│   ├── api_keys.py         # Shareable memory API keys
│   ├── webapp/             # Consumer web UI (Upload, Memory, Share)
│   └── dashboard/          # Admin dashboard (5 pages)
├── search.py               # TF-IDF semantic search
├── query_lang.py           # Graph query language (DSL)
├── federation.py           # Cross-instance sharing
├── plugins/                # Hook-based plugin system
├── viz/                    # Force-directed graph visualization
├── adapters.py             # Claude/Notion/GDocs platform adapters
├── context.py              # Cross-platform context writer (6 tools)
├── intelligence.py         # Gap analysis + weekly digest
├── contradictions.py       # Contradiction detection (4 types)
└── coding.py               # Coding session behavioral extraction

sdk/
├── python/                 # Python SDK (stdlib-only)
└── typescript/             # TypeScript SDK (@cortex_ai/sdk, zero deps)

deploy/
├── helm/                   # Kubernetes Helm chart
├── terraform/              # AWS (ECS) + GCP (Cloud Run) modules
├── grafana/                # 3 Grafana dashboards
├── Caddyfile + nginx.conf  # Reverse proxy configs
└── cortex.service          # systemd unit

spec/
├── upai-v1.0.md            # Protocol specification
└── openapi.json            # OpenAPI 3.1 API spec

tests/                      # 2,138 tests across 75+ files
```

**Zero required external dependencies.** All crypto (Ed25519, HMAC-SHA256, PBKDF2, base58btc), HTTP serving, search (TF-IDF), graph layout (Fruchterman-Reingold), metrics (Prometheus text format), and tracing (W3C Trace Context) use Python stdlib only.

**Optional:** `psycopg` (PostgreSQL), `psycopg_pool` (connection pool), `numpy` (10x faster layout), `pypdf` (better PDF extraction), `locust` (load testing).

---

## Version History

| Version | What Changed |
|---------|-------------|
| v1.4.1 | **Data Import + Shareable Memory API** — PDF/DOCX resume upload, LinkedIn data export + URL import, GitHub repo import, shareable memory API with 4 policies and 4 formats, public `GET /api/memory/{key}` endpoint. 2,138 tests. |
| v1.4.0 | **Consumer Web UI** — Upload (drag-drop with auto-detection), My Memory (interactive canvas graph), Share (multi-platform export with privacy levels). 2,063 tests. |
| v1.3.0 | **Advanced Features** — Semantic search, plugin system, query language, federation, Python SDK, Grafana dashboards, Helm chart, Terraform, tracing, Swagger UI, error hints, load testing, examples. 2,032 tests. |
| v1.2.0 | **Production Hardening** — RBAC, audit ledger, HTTP caching, webhook resilience, SSE, OAuth, encryption, rate limiting, CSRF/SSRF, SQLite + PostgreSQL backends, Python + TypeScript SDKs, Prometheus metrics, admin dashboard. 1,710 tests. |
| v1.1.0 | **UPAI Protocol + CaaS API** — DID identity, signed tokens, key rotation, 18 HTTP endpoints, JSON Schema validation, OpenAPI spec. 796 tests. |
| v1.0.0 | **First release** — Knowledge graph, temporal tracking, coding extraction, cross-platform context, visualization. 618 tests. |

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on setting up a development environment, running tests, and submitting pull requests. Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

---

## License

MIT — See [LICENSE](LICENSE)

## Author

Created by [@Junebugg1214](https://github.com/Junebugg1214)
