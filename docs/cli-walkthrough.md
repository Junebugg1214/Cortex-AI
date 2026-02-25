# CLI Walkthrough

A guided tour of every major `cortex` command with annotated output.

> **Install first:** `pip install cortex-identity`
> **Full help:** `cortex --help` or `cortex <command> --help`

---

## 1. Extract & Import

### Extract a knowledge graph from chat exports

```bash
cortex extract chatgpt-export.zip -o context.json
```

```
Extracting from chatgpt-export.zip (format: auto-detected as openai)
  ✓ 1,247 messages across 83 conversations
  ✓ 142 nodes extracted (16 extraction methods)
  ✓ 87 edges inferred (co-occurrence + pattern rules)
Wrote context.json (schema 6.0)
```

Supported formats: ChatGPT (`.zip`), Claude (`.json`), Gemini, Perplexity, plain text, JSONL. Format is auto-detected, or force it with `--format`.

### One-step migrate to a platform

```bash
cortex migrate chatgpt-export.zip --to claude -o ./output
```

```
Extracting → Building graph → Exporting for claude
  Wrote output/MEMORY.md
  Wrote output/context.json
```

This combines `extract` + `import` into a single step. The `--to` flag accepts: `claude`, `notion`, `gdocs`, `system-prompt`, `summary`, `full`, `all`.

### Import an existing graph to a platform format

```bash
cortex import context.json --to system-prompt -o ./output
```

```
Exporting context.json for system-prompt
  Wrote output/system-prompt.txt (2.4 KB)
```

---

## 2. Identity Management

### Initialize your cryptographic identity

```bash
cortex identity --init --name "Jane Doe"
```

```
Created new UPAI identity:
  DID:    did:cortex:z6Mkf5rGMoatrSj1f...
  Name:   Jane Doe
  Key:    Ed25519 (stored in ~/.cortex/identity.json)
```

Your identity is a W3C Decentralized Identifier (DID) with an Ed25519 signing key. It's stored locally and never sent anywhere.

### View your identity

```bash
cortex identity --show
```

```
DID:      did:cortex:z6Mkf5rGMoatrSj1f...
Name:     Jane Doe
Created:  2026-02-25T10:30:00Z
Keys:     1 active, 0 revoked
```

### Export your DID document

```bash
cortex identity --did-doc
```

```json
{
  "@context": ["https://www.w3.org/ns/did/v1"],
  "id": "did:cortex:z6Mkf5rGMoatrSj1f...",
  "verificationMethod": [{
    "id": "#key-1",
    "type": "Ed25519VerificationKey2020",
    "publicKeyMultibase": "z6Mkf5rGMoatrSj1f..."
  }],
  "authentication": ["#key-1"]
}
```

---

## 3. Server

### Start the CaaS API server

```bash
cortex serve context.json --port 8421 --enable-webapp --enable-sse --enable-metrics
```

```
Cortex CaaS server starting...
  Context: context.json (142 nodes, 87 edges)
  Identity: did:cortex:z6Mkf5rGMoatrSj1f...
  Storage: json (default)
  Endpoints:
    API:        http://localhost:8421
    Web UI:     http://localhost:8421/app
    Dashboard:  http://localhost:8421/dashboard
    Swagger:    http://localhost:8421/docs
    SSE:        http://localhost:8421/events
    Metrics:    http://localhost:8421/metrics
  Press Ctrl+C to stop
```

**Key flags:**

| Flag | Description |
|------|-------------|
| `--port` | Listen port (default: 8421) |
| `--enable-webapp` | Serve the consumer web UI at `/app` |
| `--enable-sse` | Enable Server-Sent Events at `/events` |
| `--enable-metrics` | Enable Prometheus metrics at `/metrics` |
| `--storage sqlite` | Use SQLite backend (`--db-path cortex.db`) |
| `--storage postgres` | Use PostgreSQL backend (`--db-url "dbname=cortex"`) |

### Use a different storage backend

```bash
# SQLite (good for single-user, persistent storage)
cortex serve context.json --storage sqlite --db-path cortex.db

# PostgreSQL (production deployments)
cortex serve context.json --storage postgres --db-url "dbname=cortex user=cortex"
```

---

## 4. Grants (Access Tokens)

### Create a grant

```bash
cortex grant --create --audience "Claude" --policy professional --ttl 48
```

```
Grant created:
  ID:       grant_a1b2c3d4
  Audience: Claude
  Policy:   professional
  Scopes:   context:read, identity:read, versions:read
  Expires:  2026-02-27T10:30:00Z
  Token:    eyJ0eXAiOiJKV1QiLCJhbGciOi...

Use this token in the Authorization header:
  Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOi...
```

### List active grants

```bash
cortex grant --list
```

```
ID              Audience    Policy        Scopes                          Expires
grant_a1b2c3d4  Claude      professional  context:read,identity:read,...  2026-02-27
grant_e5f6g7h8  Cursor      technical     context:read                    2026-02-26
```

### Revoke a grant

```bash
cortex grant --revoke grant_a1b2c3d4
```

```
Grant grant_a1b2c3d4 revoked.
```

---

## 5. Query & Analysis

### Graph statistics

```bash
cortex stats context.json
```

```
Graph Statistics:
  Nodes:       142
  Edges:       87
  Avg degree:  1.23
  Components:  3

Tag Distribution:
  technical_expertise:    38 (26.8%)
  professional_context:   24 (16.9%)
  active_priorities:      18 (12.7%)
  identity:               12 (8.5%)
  domain_knowledge:       11 (7.7%)
  ...
```

### Semantic search

```bash
cortex search context.json "machine learning"
```

```
Search results for "machine learning" (TF-IDF ranked):
  1. [technical_expertise] Machine Learning (0.95)  — "Experience with PyTorch..."
  2. [domain_knowledge] NLP Techniques (0.82)       — "Applied transformers..."
  3. [active_priorities] ML Pipeline Project (0.78)  — "Building an end-to-end..."
```

### Graph traversal

```bash
# Find neighbors of a node
cortex query context.json --neighbors "Python"
```

```
Neighbors of "Python":
  → [uses] Django (weight: 0.8)
  → [uses] FastAPI (weight: 0.7)
  → [applies_to] ML Pipeline Project (weight: 0.6)
  ← [requires] Senior Engineer at Acme Corp (weight: 0.9)
```

```bash
# Find shortest path between two nodes
cortex query context.json --path "Python" "Healthcare"
```

```
Path: Python → ML Pipeline Project → Healthcare Domain
  Length: 2 hops
```

### Query language

```bash
cortex query context.json "FIND tag=technical_expertise confidence>=0.8"
```

```
6 nodes matched:
  Python (0.95)
  Kubernetes (0.90)
  PostgreSQL (0.88)
  TypeScript (0.85)
  Docker (0.83)
  React (0.80)
```

### Gap analysis

```bash
cortex gaps context.json
```

```
Knowledge Gaps Detected:
  ⚠ Isolated node: "Rust" — no connections to projects or roles
  ⚠ Low confidence cluster: 4 nodes below 0.5 threshold
  ⚠ Missing temporal data: 12 nodes have no timestamps
  ⚠ Weak connection: "Machine Learning" ↔ "Healthcare" (weight: 0.2)
```

### Visualize the graph

```bash
cortex viz context.json -o graph.html
```

```
Generated interactive graph visualization:
  Nodes: 142, Edges: 87
  Wrote graph.html (1.2 MB)
  Open in browser: file:///path/to/graph.html
```

---

## 6. Versioning

### Commit a version snapshot

```bash
cortex commit context.json -m "Added June ChatGPT export"
```

```
Version committed:
  ID:      ver_x9y8z7w6
  Message: Added June ChatGPT export
  Nodes:   142 → 168 (+26)
  Edges:   87 → 104 (+17)
  Signed:  did:cortex:z6Mkf5rGMoatrSj1f...
```

### View version history

```bash
cortex log --limit 5
```

```
ver_x9y8z7w6  2026-02-25  Added June ChatGPT export (168 nodes)
ver_a1b2c3d4  2026-02-20  Initial extraction from resume (142 nodes)
ver_e5f6g7h8  2026-02-18  First commit (89 nodes)
```

### Diff two versions

```bash
cortex diff context.json --compare old-context.json
```

```
Diff: ver_x9y8z7w6 ↔ ver_a1b2c3d4
  Added:    26 nodes, 17 edges
  Removed:  0 nodes, 0 edges
  Modified: 3 nodes (confidence changes)
```

---

## 7. Cross-Platform Context Sync

### Write context to all AI coding tools

```bash
cortex context-write context.json --platforms all --project ~/myproject
```

```
Writing context to AI coding tools:
  ✓ Claude Code:    ~/.claude/MEMORY.md (global)
  ✓ Claude Code:    ~/myproject/.claude/MEMORY.md (project)
  ✓ Cursor:         ~/myproject/.cursor/rules/cortex.mdc
  ✓ GitHub Copilot: ~/myproject/.github/copilot-instructions.md
  ✓ Windsurf:       ~/myproject/.windsurfrules
  ✓ Gemini CLI:     ~/myproject/GEMINI.md
```

The writer uses `<!-- CORTEX:START -->` / `<!-- CORTEX:END -->` markers so your hand-written rules are never overwritten.

### Install a Claude Code context hook

```bash
cortex context-hook install context.json --policy professional
```

```
Installed context hook for Claude Code.
Your Cortex context will be auto-injected into every session.
```

---

## 8. Coding Session Extraction

### Discover coding sessions

```bash
cortex extract-coding --discover
```

```
Found coding sessions:
  ~/.claude/projects/myproject/*.jsonl (12 sessions, 847 messages)
  ~/.claude/projects/other/*.jsonl (3 sessions, 124 messages)
```

### Extract from coding sessions

```bash
cortex extract-coding --discover --project ~/myproject -o coding.json
```

```
Extracted from 12 Claude Code sessions:
  Technologies: 8 nodes (Python, TypeScript, Docker, ...)
  Tools: 5 nodes (pytest, npm, git, ...)
  Commands: 4 nodes (docker compose, terraform, ...)
Wrote coding.json
```

---

## Command Reference

Run `cortex --help` for the full list. For any command, add `--help` for detailed usage:

```bash
cortex serve --help
cortex extract --help
cortex query --help
```

Enable shell autocomplete for tab-completion of commands and flags:

```bash
# Bash
eval "$(cortex completion --shell bash)"

# Zsh
eval "$(cortex completion --shell zsh)"

# Fish
cortex completion --shell fish | source
```

## Next Steps

- [Python SDK Quickstart](quickstart-python.md) — programmatic access
- [TypeScript SDK Quickstart](quickstart-typescript.md) — TypeScript/Node.js access
- [Error Reference](error-guide.md) — all 17 UPAI error codes explained
- [Interactive API Docs](http://localhost:8421/docs) — Swagger UI (start server first)
