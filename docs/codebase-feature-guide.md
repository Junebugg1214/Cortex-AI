# Cortex Codebase Feature Guide

This guide explains, in simple terms, what this application does, what features exist in the code, and how to use them.

## What this application does

Cortex is a local-first memory system for AI tools.

It takes your data (chat exports, coding session data, resumes, LinkedIn/GitHub imports), extracts identity and context signals, stores them in a knowledge graph, and lets you:

- Query and analyze that graph
- Export filtered versions to different platforms
- Serve it over an API (Context-as-a-Service)
- Manage access with identity, grants, policies, and audit controls

In short: one portable memory graph, controlled by you.

## Main interfaces

1. CLI (`cortex ...`) for extraction, analysis, sync, and security operations
2. CaaS server (`cortex serve ...`) for HTTP access and automation
3. Web app (`/app`) and dashboard (`/dashboard`) for UI workflows
4. SDKs (Python and TypeScript) for app integrations

## Feature inventory and how to use each

## 1) Import and extraction

### What it does

Reads input data and converts it to graph/context JSON.

### Implemented sources

- Chat exports (auto/explicit format handling)
  - OpenAI/ChatGPT exports
  - Gemini exports
  - Perplexity exports
  - JSONL/messages/plain text inputs
- Resume files
  - PDF (library-assisted when available, stdlib fallback)
  - DOCX (stdlib zip/xml parser)
- LinkedIn
  - Data export ZIP parsing
  - Limited public profile URL fetch
- GitHub import endpoint (server)
- Claude Code session extraction (`extract-coding`)

### How to use

```bash
# Full extract+export pipeline (default behavior when first arg is a file)
cortex chatgpt-export.zip --to all -o ./output

# Extract only
cortex extract chatgpt-export.zip -o context.json

# Extract coding sessions (auto-discover)
cortex extract-coding --discover --output coding_context.json

# Continuous coding extraction
cortex extract-coding --watch --output coding_context.json
```

## 2) Export and platform adapters

### What it does

Takes a graph/context and exports platform-specific formats, optionally with disclosure filtering and signatures.

### Implemented adapter targets

- `claude`
- `notion`
- `gdocs`
- `system-prompt`

### How to use

```bash
# Export for specific target with policy filtering
cortex sync context.json --to claude --policy professional -o ./output

# Import a platform export back into graph format
cortex pull notion_page.md --from notion -o graph.json
```

## 3) Graph exploration and analysis

### What it does

Lets you inspect graph content, relationships, and quality.

### Implemented analysis commands

- `stats` for graph counts/distribution
- `query` for node lookup, neighbors, path, category, changed-since, strongest/weakest, isolated, related, components, NL-style query
- `timeline` for chronological view
- `contradictions` for conflict detection
- `drift` for graph-vs-graph identity drift
- `gaps` for gap detection (missing categories, low confidence, isolated, stale)
- `digest` for snapshot comparison summary
- `viz` for HTML/SVG graph rendering

### How to use

```bash
cortex stats context.json
cortex query context.json --node "Python"
cortex query context.json --neighbors "Python"
cortex query context.json --path "Python" "Healthcare"
cortex timeline context.json --format md
cortex contradictions context.json --severity 0.5
cortex drift current.json --compare previous.json
cortex gaps context.json
cortex digest current.json --previous previous.json
cortex viz context.json --output graph.html
```

## 4) Identity, security, and trust model (UPAI)

### What it does

Adds ownership and access controls to your graph operations.

### Implemented security features

- DID identity generation and loading
- Key rotation and key history
- Signed grant tokens (Ed25519/HMAC modes)
- Scope-based access and RBAC role mapping
- Disclosure policies (builtin + custom registry)
- Verifiable credentials issuance/verification/storage
- Encrypted identity backup and recovery phrase generation
- Signature and integrity verification for signed exports

### How to use

```bash
# Create identity
cortex identity --init --name "Your Name"

# Show identity / DID document
cortex identity --show
cortex identity --did-doc

# Rotate identity key
cortex rotate --reason rotated

# Create grant token
cortex grant --create --audience "my-app" --policy professional --ttl 24

# List/revoke grants
cortex grant --list
cortex grant --revoke <grant_id>

# Verify signed export
cortex verify signed_export.json
```

## 5) Versioning and history

### What it does

Stores graph snapshots and lets you inspect history and diffs.

### How to use

```bash
cortex commit context.json -m "Initial snapshot"
cortex log --limit 20
```

For API-based diffs/history, use server endpoints under `/versions` and `/versions/diff`.

## 6) Context-as-a-Service server

### What it does

Runs an HTTP server over your graph so other tools can read/use it under your policy and token controls.

### Core endpoints (OpenAPI-covered)

- `/`
- `/.well-known/upai-configuration`
- `/identity`
- `/grants`
- `/context`, `/context/compact`, `/context/nodes`, `/context/edges`, `/context/stats`
- `/versions`, `/versions/{id}`, `/versions/diff`
- `/webhooks`

### Additional implemented server capabilities

- Context mutations/search/batch/path/neighbors
- Policies CRUD
- Credentials APIs and verify flow
- Audit endpoints (query/verify/export)
- SSE stream (`/events`)
- Metrics endpoint (`/metrics`)
- OAuth provider and token exchange flows
- Federation peer list/export/import
- Shareable API keys and public memory endpoint
- Timeline APIs
- Profile/public profile endpoints (`/p/{handle}`)
- Web app and dashboard API routing

### How to use

```bash
cortex serve context.json --port 8421 --storage sqlite --enable-webapp --enable-sse --enable-metrics
```

Then open:

- Web app: `http://localhost:8421/app`
- Dashboard: `http://localhost:8421/dashboard`
- API docs: `http://localhost:8421/docs`

## 7) Web app and dashboard

### What it does

Provides GUI workflows for upload/import, sharing, profile management, and admin operations.

### Web app (`/app`) capabilities

- Upload/import data
- Explore memory graph
- Share/export memory formats
- API key management
- Profile management and QR utilities
- Signup/login/logout endpoints

### Dashboard (`/dashboard`) capabilities

- Identity and graph stats
- Graph explorer
- Grant/token management
- Version history and diff
- Audit visibility
- Webhook health/retry
- Graph health/changelog
- Archive export/import
- Configuration and auth checks

## 8) Webhooks, events, resilience, and rate limiting

### What it does

Supports event delivery to external systems and protects server reliability.

### Implemented features

- Signed webhook payloads (HMAC-SHA256)
- Background worker with retries and jitter backoff
- Circuit breaker + dead-letter queue behavior
- Tiered rate limiting (auth/write/read tiers)
- SSE support with event infrastructure

### How to use

- Register webhooks via CLI/API
- Consume events via webhook callbacks or `/events`

## 9) Public memory API keys

### What it does

Creates shareable key-based access (`/api/memory/{key}`) with policy and output format.

### Formats supported in renderer

- `json`
- `claude_xml`
- `system_prompt`
- `markdown`
- `jsonresume`

### How to use

- Create/list/revoke via web app or API (`/api/keys`)
- Fetch via public memory path (`/api/memory/{key}`)

## 10) Cross-tool context file writing

### What it does

Writes compact context into common AI coding tool files with non-destructive markers.

### Supported targets

- `claude-code`
- `claude-code-project`
- `cursor`
- `copilot`
- `windsurf`
- `gemini-cli`

### How to use

```bash
# Write for selected platforms
cortex context-write context.json --platforms claude-code cursor copilot

# Write for all supported targets
cortex context-write context.json --platforms all

# Watch and auto-refresh
cortex context-write context.json --platforms all --watch
```

## 11) Automation helpers

### What it does

Lets you keep graph/context updated over time.

### Commands

- `watch` (monitor directory for new exports)
- `sync-schedule` (run periodic sync plan)

### How to use

```bash
cortex watch ./exports --graph context.json --interval 30
cortex sync-schedule --config sync.json --once
```

## 12) SDK integrations

### Python SDK

- Provides `CortexClient` for core CaaS endpoints
- Includes pagination iterators and typed errors

### TypeScript SDK

- Provides `CortexClient` with async generators
- Supports core CaaS calls and metrics/discovery flows

### How to use

- Python package under `sdk/python`
- TypeScript package under `sdk/typescript`

## Typical end-to-end usage flow

```bash
# 1) Build context graph from source data
cortex migrate chatgpt-export.zip -o ./output --schema v5

# 2) Initialize identity
cortex identity --init --name "Your Name"

# 3) Version snapshot
cortex commit output/context.json -m "initial graph"

# 4) Serve API + web UI
cortex serve output/context.json --enable-webapp --storage sqlite

# 5) Create controlled access token
cortex grant --create --audience "my-agent" --policy technical
```

## Important notes from code behavior

- If you pass a file path as first CLI arg without a subcommand, CLI routes to `migrate`.
- Many server features exist beyond the minimal OpenAPI file; route handlers in `cortex/caas/server.py` are the broader source of truth.
- Security model combines disclosure policies + scoped grants + signature checks + audit support.
- Storage backends are JSON/SQLite/Postgres in server/grant/audit paths.

## Primary code references

- `cortex/cli.py`
- `cortex/caas/server.py`
- `cortex/caas/importers.py`
- `cortex/adapters.py`
- `cortex/extract_memory.py`
- `cortex/graph.py`
- `cortex/upai/tokens.py`
- `cortex/upai/disclosure.py`
- `cortex/upai/credentials.py`
- `cortex/upai/backup.py`
- `cortex/federation.py`
- `sdk/python/cortex_sdk/client.py`
- `sdk/typescript/src/client.ts`
- `spec/openapi.json`
