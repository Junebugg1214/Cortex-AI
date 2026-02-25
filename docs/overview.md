# Cortex — What It Is

Cortex is a tool that takes everything AI platforms know about you — your ChatGPT conversations, Claude chats, coding sessions — and builds a **portable knowledge graph** that **you own**.

Instead of each AI having its own incomplete picture of you, Cortex creates one unified identity you can take anywhere.

---

## How to Use It

### 1. Extract your data

Export your chat history from ChatGPT (as a `.zip`), Claude, Gemini, or any supported platform. Then run:

```bash
pip install cortex-identity
cortex chatgpt-export.zip -o context.json
```

This reads your conversations and builds a knowledge graph — nodes like "Python", "healthcare", "prefers concise answers" connected by relationships.

### 2. Push it to another platform

```bash
cortex sync context.json --to claude --policy professional -o ./output
```

This takes your graph, filters it through a disclosure policy (so you control what's shared), and exports it in a format the target platform understands.

### 3. Sign and version it

```bash
cortex identity --init --name "Your Name"
cortex commit context.json -m "Initial context"
```

This creates a cryptographic identity (`did:key`) and version-controls your graph like git. You can prove the data is yours and hasn't been tampered with.

### 4. Serve it as an API (Context-as-a-Service)

Instead of exporting files and manually copying them, you can run a server that lets AI platforms pull your context directly over HTTP.

```bash
# Start the server
cortex serve context.json --port 8421

# Create an access token for a platform
cortex grant --create --audience "Claude" --policy professional
```

This is the **Context-as-a-Service (CaaS) API** — the idea is that instead of you pushing data to each platform, platforms come to you.

---

## The CaaS API — How It Works

The Context-as-a-Service API turns Cortex from a CLI tool into a server that AI platforms can talk to. Here's the full picture.

### Starting the server

```bash
cortex serve context.json --port 8421
```

This starts an HTTP server on `localhost:8421` that serves your knowledge graph. Nothing is exposed to the internet unless you choose to — it runs locally by default.

### Giving a platform access

You control who can access your data by creating **grant tokens**. Each token is cryptographically signed and scoped:

```bash
# Give Claude read access with the "professional" disclosure policy
cortex grant --create --audience "Claude" --policy professional

# Give a different platform access with a different policy
cortex grant --create --audience "Cursor" --policy technical

# See all active grants
cortex grant --list

# Revoke access
cortex grant --revoke <grant_id>
```

Each grant specifies **what** the platform can see (disclosure policy) and **what** it can do (scopes like `context:read`, `versions:read`). The token expires automatically.

### What platforms can do with a token

Once a platform has a token, it includes it in API requests as `Authorization: Bearer <token>`. The server verifies the signature, checks expiry and scope, then returns data filtered through the grant's disclosure policy.

**Discovery** — A platform can find out what your server offers:
- `GET /.well-known/upai-configuration` — what endpoints exist, what scopes are supported
- `GET /identity` — your W3C DID Document (public key, identity info)

**Context** — Reading your knowledge graph (requires `context:read` scope):
- `GET /context` — your full graph, filtered by the grant's disclosure policy
- `GET /context/compact` — a markdown summary (good for injecting into system prompts)
- `GET /context/nodes` — paginated list of nodes
- `GET /context/nodes/<id>` — a single node
- `GET /context/edges` — relationships between nodes
- `GET /context/stats` — graph statistics (node count, edge count, categories)

**Versions** — Viewing your identity history (requires `versions:read` scope):
- `GET /versions` — paginated version history
- `GET /versions/<id>` — a specific snapshot
- `GET /versions/diff?a=<id>&b=<id>` — what changed between two versions

**Webhooks** — Getting notified when things change:
- `POST /webhooks` — register a URL to receive notifications
- Events: `context.updated`, `version.created`, `grant.created`, `grant.revoked`, `key.rotated`, `profile.viewed`
- Payloads are signed with HMAC-SHA256 so receivers can verify they're legitimate

### Security model

- **Tokens are signed with Ed25519** — they can't be forged or tampered with
- **Every request is scoped** — a token with `context:read` can't modify anything
- **Disclosure policies filter data** — a "professional" grant never exposes private nodes
- **Tokens expire** — time-limited by default (24 hours)
- **Replay protection** — nonces prevent reusing intercepted requests
- **Key rotation** — if a key is compromised, rotate to a new one and old tokens become invalid

```bash
cortex rotate  # Generate new keypair, revoke old one
```

### Example: what a platform sees

A platform with a "professional" grant calling `GET /context/compact` might get:

```
Skills: Python, TypeScript, distributed systems
Experience: 8 years software engineering, healthcare AI
Current focus: Building portable identity protocol
Communication: Prefers concise, technical responses
```

The same graph with a "minimal" grant would return just labels and categories — no descriptions, no metadata, no relationships.

### Full API spec

The complete API is documented in OpenAPI 3.1 format at [`spec/openapi.json`](../spec/openapi.json). The underlying protocol is specified in [`spec/upai-v1.0.md`](../spec/upai-v1.0.md).

---

## Keeping Your Graph Up to Date

For chat platforms (ChatGPT, Claude, Gemini), the extraction process is **manual**. When you have new conversations, export your data again and merge it with your existing graph:

```bash
cortex chatgpt-export-new.zip --merge context.json -o context.json
```

Repeat this periodically (weekly, monthly) to keep your knowledge graph current. These platforms don't offer live APIs for conversations, so export-and-merge is the workflow for now.

For **Claude Code**, Cortex can extract in real-time. It watches your coding sessions as they happen and automatically merges new signals into your graph:

```bash
cortex extract-coding --watch -o context.json
```

---

## The Key Ideas

- **You own your data** — it's a local file, not locked in someone's cloud
- **Portable** — works across ChatGPT, Claude, Gemini, Cursor, Copilot, and more
- **Privacy controls** — disclosure policies let you share "professional" info with one platform and "technical" info with another
- **Cryptographically signed** — proves the data is yours and unchanged
- **API-ready** — platforms can pull your context over HTTP instead of you copy-pasting
- **Zero dependencies** — runs with just Python's standard library

---

## Setup & Adoption

### Requirements

- Python 3.10+
- A terminal
- That's it — no accounts, no API keys, no cloud services

Optional: `pip install cortex-identity[crypto]` adds Ed25519 signatures (requires `pynacl`).

### Time to First Result: ~5 Minutes

1. **Install** (~30 seconds): `pip install cortex-identity`
2. **Export from ChatGPT** (~2 minutes): Settings > Data Controls > Export Data > wait for email > download zip
3. **Run extraction** (~10 seconds): `cortex chatgpt-export.zip -o context.json`
4. **See what you got** (~10 seconds): `cortex stats context.json`

### Who It's For Right Now

Developers and power users who use multiple AI platforms, are comfortable with CLI tools, and care about owning their data. If you've felt the pain of starting over with a new AI because it doesn't know you — Cortex solves that.

### Access Paths

Cortex is available through multiple interfaces:

- **CLI** — Full-featured command line for power users and automation
- **Web App** — Consumer UI at `/app` for uploading data, exploring your memory graph, sharing context, and managing public profiles
- **Dashboard** — Admin UI at `/dashboard` for grants, versions, audit, health monitoring, and server configuration
- **API** — 50+ REST endpoints for programmatic access, plus SSE for real-time events
- **SDKs** — Python and TypeScript client libraries for integration

### Known Constraints

- Chat platform exports are manual (export zip, run command, repeat) — no live API from ChatGPT/Gemini
- Claude bulk export requires `.jsonl` session files from Claude Code
