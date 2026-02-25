# Cortex User Guide

## Overview

Cortex is a portable identity graph system. It extracts who you are from your
AI conversations (ChatGPT, Gemini, Claude, etc.), stores it as a structured
knowledge graph, and lets you share filtered views with other platforms.

**Key concepts:**

- **Graph** — Your identity as nodes (facts about you) and edges (relationships
  between facts). Schema v5/v6.
- **Identity** — A DID (Decentralized Identifier) that proves ownership. Uses
  Ed25519 or HMAC-SHA256 signing.
- **Disclosure** — Policies that filter what a consumer sees: `full`,
  `professional`, `technical`, `minimal`.
- **CaaS** — Context-as-a-Service. An HTTP API that serves your graph to
  authorized consumers via grant tokens.

---

## Installation

```bash
# Clone the repository
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI

# No external dependencies required — stdlib only
python3 -c "from cortex.cli import main; print('OK')"
```

---

## Quick Start

### 1. Extract context from a chat export

```bash
# ChatGPT export
python3 -m cortex.cli migrate chatgpt-export.zip --to all -o ./output --schema v5

# Gemini export
python3 -m cortex.cli migrate gemini-takeout.json --to claude -o ./output

# Plain text
python3 -m cortex.cli extract notes.txt -o context.json
```

### 2. Create an identity

```bash
python3 -m cortex.cli identity --init --name "Your Name"
# Output: did:key:z6Mk...
```

### 3. Start the CaaS server

```bash
python3 -m cortex.cli serve output/context.json --storage sqlite
# CaaS API: http://127.0.0.1:8421
# Dashboard: http://127.0.0.1:8421/dashboard
```

### 4. Create a grant token

```bash
python3 -m cortex.cli grant --create --audience "claude.ai" --policy professional
# Gives a Bearer token for API access
```

---

## CLI Reference

### Core Commands

| Command | Description |
|---------|-------------|
| `migrate <file>` | Full pipeline: extract + export to all platforms |
| `extract <file>` | Extract context from export file to JSON |
| `import <file>` | Export context JSON to platform formats |
| `pull <file> --from <platform>` | Import a platform export back into a graph |

### Graph Commands

| Command | Description |
|---------|-------------|
| `query <file>` | Query nodes, edges, paths in a graph |
| `stats <file>` | Show graph statistics |
| `timeline <file>` | Generate timeline from graph |
| `contradictions <file>` | Detect contradictions |
| `drift <file> --compare <file2>` | Compute identity drift |
| `gaps <file>` | Analyze knowledge gaps |
| `digest <file> --previous <file2>` | Weekly digest comparing two snapshots |

### Identity & Versioning

| Command | Description |
|---------|-------------|
| `identity --init` | Generate a new UPAI identity |
| `identity --show` | Show current identity |
| `commit <file> -m "msg"` | Version a graph snapshot |
| `log` | Show version history |
| `rotate` | Rotate identity key |

### Sharing & Sync

| Command | Description |
|---------|-------------|
| `sync <file> --to <platform>` | Disclosure-filtered export |
| `verify <file>` | Verify a signed export |
| `serve <file>` | Start CaaS API server |
| `grant --create` | Create a grant token |
| `grant --list` | List grants |
| `grant --revoke <id>` | Revoke a grant |

### Visualization

| Command | Description |
|---------|-------------|
| `viz <file>` | Render graph as HTML/SVG |
| `dashboard <file>` | Launch local dashboard (standalone) |

### Pull Adapters

Import data from platform exports back into a Cortex graph:

```bash
# From Notion markdown export
python3 -m cortex.cli pull notion_page.md --from notion -o graph.json

# From Notion database JSON
python3 -m cortex.cli pull notion_database.json --from notion -o graph.json

# From Google Docs HTML export
python3 -m cortex.cli pull google_docs.html --from gdocs -o graph.json

# From Claude memories JSON
python3 -m cortex.cli pull claude_memories.json --from claude -o graph.json
```

---

## Dashboard

The CaaS server includes a built-in web dashboard at `/dashboard`.

### Accessing the Dashboard

1. Start the CaaS server: `python3 -m cortex.cli serve context.json`
2. Open `http://localhost:8421/dashboard` in your browser
3. Enter the dashboard password (displayed at server startup)

### Dashboard Pages

- **Overview** — DID info, graph stats, tag distribution, recent audit activity
- **Graph Explorer** — Interactive force-directed graph visualization with
  disclosure policy filtering, search, and node detail panel
- **Grants** — Create and revoke grant tokens with scope/policy/TTL controls
- **Versions** — Timeline of graph versions with diff comparison
- **Health** — Stale node detection, orphan analysis, confidence distribution charts, graph changelog
- **Settings** — Server config, webhook management, graph export, archive export/import

### Dashboard Authentication

The dashboard password is derived from your identity's private key. It's
displayed when you start the server. Sessions are cookie-based with 24-hour TTL,
`HttpOnly` and `SameSite=Strict` flags.

---

## Disclosure Policies

| Policy | Description | Use Case |
|--------|-------------|----------|
| `full` | Everything visible | Personal backup |
| `professional` | Work-relevant nodes, medium+ confidence | LinkedIn, resumes |
| `technical` | Skills, tools, coding style | AI coding assistants |
| `minimal` | Name and high-confidence identity only | Public profiles |

```bash
# Export with professional filter
python3 -m cortex.cli sync context.json --to claude --policy professional

# Grant with technical policy
python3 -m cortex.cli grant --create --audience "cursor.ai" --policy technical
```

---

## Storage Backends

### JSON (default)

Simple file-based storage. Good for development and small graphs.

```bash
python3 -m cortex.cli serve context.json --storage json
```

### SQLite

Thread-safe, supports audit logging and webhook delivery tracking.

```bash
python3 -m cortex.cli serve context.json --storage sqlite --db-path cortex.db
```

### PostgreSQL

Production-grade relational backend with connection pooling and hash-chained audit ledger.

```bash
pip install "cortex-identity[postgres]"
python3 -m cortex.cli serve context.json --storage postgres --db-url "host=localhost dbname=cortex"
```

---

## Web App

Start the server with `--enable-webapp` and open `http://localhost:8421/app`.

```bash
python3 -m cortex.cli serve context.json --enable-webapp
```

### Pages

- **Upload** — Drag-and-drop files (JSON, PDF, DOCX, zip), GitHub and LinkedIn URL import cards, API key management
- **My Memory** — Interactive canvas graph with force-directed layout, zoom/pan, click-to-select, tag-colored nodes, search and filters
- **Share** — Export to Claude, Notion, Google Docs, or system prompt format with privacy level selection and live preview
- **Profile** — Create and manage public profiles (see below)

---

## Public Profiles

Create shareable public profiles accessible at `/p/{handle}`.

### Features

- **Multi-profile** — Create multiple profiles per identity, each with its own disclosure policy (e.g., one for recruiters, one for open-source)
- **Public URLs** — Each profile gets a `/p/{handle}` route accessible without authentication
- **QR codes** — Generate QR codes for profile URLs directly in the web app
- **`profile.viewed` webhook** — Get notified when someone views your public profile

### Setup

1. Start the server with `--enable-webapp`
2. Open `/app` and navigate to the **Profile** page
3. Create a profile: choose a handle, select a disclosure policy, add a bio
4. Share the URL or QR code

---

## Archive Export/Import

Export your full graph as a ZIP archive for backup, migration, or sharing.

- **Export** — From the Dashboard Settings page, click "Export Archive" to download a `.zip` containing your graph, identity, and configuration
- **Import** — Upload a `.zip` archive to restore or migrate a graph to a new instance

---

## Shareable Memory API

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

---

## Security Notes

- The CaaS server binds to `127.0.0.1` only — not accessible from the network
- Grant tokens use HMAC-SHA256 or Ed25519 signatures
- All tokens have configurable TTL (1 hour to 1 year)
- Dashboard sessions use `HttpOnly; SameSite=Strict` cookies
- Rate limiting protects against brute force (configurable)
- No external dependencies — reduces supply chain risk
