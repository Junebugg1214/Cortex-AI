# Cortex Architecture

## System Overview

```
    Chat Exports          Cortex Core            Consumers
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │ ChatGPT .zip │     │              │     │ Claude.ai    │
  │ Gemini .json │────>│  Extractor   │     │ Cursor       │
  │ Claude .jsonl│     │      │       │     │ Notion       │
  └──────────────┘     │      v       │     │ Google Docs  │
                       │  CortexGraph │────>│              │
  Platform Exports     │   (v5/v6)    │     └──────────────┘
  ┌──────────────┐     │      │       │
  │ Notion .md   │────>│  Identity    │     ┌──────────────┐
  │ GDocs .html  │pull │  Versioning  │     │ CaaS API     │
  │ Claude .json │     │  Disclosure  │────>│   :8421      │
  └──────────────┘     │              │     │ + Dashboard  │
                       └──────────────┘     └──────────────┘
```

## Core Modules

### `cortex/graph.py` — CortexGraph

The central data structure. A directed graph with typed nodes and edges.

- **Node**: `id`, `label`, `tags[]`, `confidence`, `brief`, `full_description`,
  `mention_count`, `metrics[]`, `timeline[]`, `first_seen`, `last_seen`
- **Edge**: `id`, `source_id`, `target_id`, `relation`, `confidence`
- **Schema**: v5 (current), v6 (compatible extension)

Key operations: `add_node()`, `add_edge()`, `find_nodes()`, `get_neighbors()`,
`stats()`, `export_v5()`, `from_v5_json()`, `graph_health()`, `diff_graphs()`.

### `cortex/extract_memory.py` — AggressiveExtractor

Extracts identity signals from chat transcripts. Handles OpenAI, Gemini,
Perplexity, JSONL, API logs, plain text formats.

### `cortex/import_memory.py` — NormalizedContext

Intermediate representation between v4 categories and platform exports.
Export functions: `export_claude_preferences()`, `export_notion()`, etc.

### `cortex/compat.py` — Schema Compatibility

- `upgrade_v4_to_v5(v4_dict)` → `CortexGraph`
- `downgrade_v5_to_v4(graph)` → `dict`

### `cortex/upai/` — Identity & Protocol

- **`identity.py`** — `UPAIIdentity` with Ed25519/HMAC signing, DID generation
- **`tokens.py`** — `GrantToken` creation, signing, verification
- **`disclosure.py`** — `DisclosurePolicy`, `apply_disclosure()`, built-in
  policies
- **`versioning.py`** — `VersionStore` with commit/checkout/diff/log
- **`keychain.py`** — Key rotation with revocation proofs
- **`webhooks.py`** — Webhook registration and event types
- **`pagination.py`** — Cursor-based pagination for API responses

### `cortex/adapters.py` — Platform Adapters

Push/pull adapters for each platform:

| Adapter | Push | Pull |
|---------|------|------|
| `ClaudeAdapter` | preferences.txt + memories.json | memories.json → graph |
| `SystemPromptAdapter` | system_prompt.txt | XML tags → graph |
| `NotionAdapter` | notion_page.md + database.json | .md or .json → graph |
| `GDocsAdapter` | google_docs.html | HTML → graph |

### `cortex/search.py` — Semantic Search

TF-IDF ranked search across all node fields (stdlib-only, no external dependencies).

### `cortex/query_lang.py` — Graph Query Language

DSL parser and executor: `FIND`, `NEIGHBORS`, `PATH`, `SEARCH` operations.

### `cortex/federation.py` — Cross-Instance Federation

Export/import graphs between Cortex instances with peer management.

### `cortex/plugins/` — Plugin System

12 hook points for extending server behavior (on_request, on_response, on_graph_update, etc.).

### `cortex/caas/` — Context-as-a-Service

- **`server.py`** — HTTP API server (50+ endpoints) + dashboard + webapp routes
- **`storage.py`** — Abstract store interfaces
- **`sqlite_store.py`** — SQLite implementations for grants, webhooks, audit
- **`postgres_store.py`** — PostgreSQL implementations with connection pooling
- **`postgres_audit_ledger.py`** — Hash-chained audit ledger for PostgreSQL
- **`rate_limit.py`** — Token bucket rate limiter
- **`webhook_worker.py`** — Background webhook delivery with retry
- **`oauth.py`** — OAuth 2.0 / OIDC with Google and GitHub providers
- **`config.py`** — INI + environment variable configuration
- **`instrumentation.py`** — Prometheus metrics (17 metrics, stdlib-only)
- **`correlation.py`** — Request correlation ID middleware
- **`archive.py`** — ZIP archive export/import
- **`qr.py`** — QR code generation for public profiles
- **`profile.py`** — Public profile management (multi-profile, `/p/{handle}`)
- **`api_keys.py`** — Shareable memory API key management
- **`dashboard/`** — Admin dashboard SPA (6 pages: Overview, Graph, Grants, Versions, Health, Settings)
- **`webapp/`** — Consumer web UI (Upload, Memory, Share, Profile)

## Data Flow

### Extract → Store → Share

```
1. Extract:  chat_export  ──> AggressiveExtractor ──> v4 dict
2. Upgrade:  v4 dict      ──> upgrade_v4_to_v5()  ──> CortexGraph
3. Version:  CortexGraph  ──> VersionStore.commit() ──> snapshot
4. Serve:    CortexGraph  ──> CaaSHandler          ──> HTTP API
5. Filter:   CortexGraph  ──> apply_disclosure()   ──> filtered graph
6. Export:   filtered      ──> adapter.push()       ──> platform files
```

### Pull (Reverse Import)

```
1. Parse:    platform_file ──> adapter.pull()       ──> v4 categories
2. Upgrade:  v4 dict       ──> upgrade_v4_to_v5()   ──> CortexGraph
3. Store:    CortexGraph   ──> export_v5()           ──> JSON file
```

## Authentication & Security

### CaaS API Authentication

Consumers authenticate via Bearer tokens (grant tokens):

```
POST /grants  ──> GrantToken.create() ──> signed JWT-like token
GET  /context  +  Authorization: Bearer <token>
               ──> GrantToken.verify_and_decode()
               ──> check scope, check revocation
               ──> apply disclosure policy from token
               ──> return filtered graph
```

### Dashboard Authentication

The dashboard uses a derived password + session cookie:

```
Password = HMAC(private_key, "cortex-dashboard")[:24]
POST /dashboard/auth { password }
  ──> DashboardSessionManager.authenticate()
  ──> Set-Cookie: cortex_session=<random_hex>; HttpOnly; SameSite=Strict
GET  /dashboard/api/*
  ──> validate session cookie
  ──> owner-level access (no scope restrictions)
```

## Design Principles

1. **Zero external dependencies** — Everything uses Python stdlib
2. **Schema compatibility** — v4 ↔ v5 ↔ v6 conversion at every boundary
3. **Privacy by default** — Disclosure policies filter before sharing
4. **Local-first** — Server binds to 127.0.0.1, no cloud dependency
5. **Portable identity** — DID-based, can be verified without Cortex
