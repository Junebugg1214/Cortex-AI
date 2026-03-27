# Cortex

**One command. All your AI context. Every tool.**

Cortex makes your AI context portable across Claude, Claude Code, ChatGPT, Codex, Gemini, Grok, Windsurf, Cursor, and Copilot without giving up control of your data.

**Status**

- self-hosted public beta
- user-owned storage
- stable local `v1` API contract

CLI is how humans curate Cortex. MCP is how AI tools consume Cortex live.

Set it up once, and every AI tool you use can know you automatically, stay up to date, and stop treating you like a stranger.

## The Problem

If you use more than one AI tool, you are probably repeating yourself constantly.

- ChatGPT knows your stack, but Claude does not.
- Claude Code knows your repo today, but Cursor still has stale rules from a month ago.
- Copilot has no idea you migrated from PostgreSQL to CockroachDB.
- Switching platforms means losing context and starting over.

Cortex fixes that by turning your AI context into something you can carry, inspect, sync, route, and audit.

## The Pitch

With Cortex, you can:

- import context from exports, project files, resumes, and git history
- write that context into the tools you use locally
- generate import-ready artifacts for tools that do not expose a stable local file path
- serve live, routed context to MCP-capable AI tools during conversations
- audit what each tool knows, what is missing, and what is stale
- teach Cortex something once and propagate it everywhere
- route different context slices to different tools instead of dumping the same blob everywhere

This is the front door:

```bash
pip install "cortex-identity[full]"

cortex portable chatgpt-export.zip --to all --project .
```

That single command can:

- extract a portable `context.json`
- write local context files for Claude Code, Codex, Cursor, Copilot, Gemini, and Windsurf
- generate import-ready artifacts for Claude, ChatGPT, and Grok
- leave everything on your machine

## The Loop

The portability story is not just file generation.

The full loop looks like this:

- humans use the CLI to import, inspect, teach, route, and sync context
- AI tools use MCP to fetch the current routed slice live while they are helping you

That means you do not have to choose between:

- local files for coding tools
- import-ready artifacts for chat tools
- live context for MCP-capable agents

Cortex can serve all three from the same portable source of truth.

### Humans curate with the CLI

```bash
cortex portable chatgpt-export.zip --to all --project .
cortex scan
cortex remember "We use Vitest now"
cortex sync --smart
```

### AI tools consume live context over MCP

```bash
cortex-mcp --config .cortex/config.toml
```

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"portability_context","arguments":{"target":"claude-code","project_dir":"/path/to/repo","smart":true}}}
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"portability_status","arguments":{"project_dir":"/path/to/repo"}}}
```

That is the real portability pitch:

**set up Cortex once, and every AI tool you use can know you automatically, always with the latest context**

## The Holy-Shit Workflow

### 1. Import once

```bash
cortex portable chatgpt-export.zip --to all --project .
```

### 2. See what every tool knows

```bash
cortex scan
```

Example shape:

```text
Found 8 AI tools:

ChatGPT      ████████████░░░░░░░░  67 facts  (export: 3 days old)
Claude Code  ████████░░░░░░░░░░░░  42 facts  (CLAUDE.md: fresh)
Cursor       ████░░░░░░░░░░░░░░░░  18 facts  (.cursor rules: stale)
Copilot      ░░░░░░░░░░░░░░░░░░░░   0 facts  (not configured)
```

### 3. Teach once

```bash
cortex remember "We migrated from PostgreSQL to CockroachDB in January"
```

By default that updates the direct-write coding tools in one pass:

- Claude Code
- Codex
- Cursor
- Copilot
- Gemini
- Windsurf

### 4. Route the right slice to each tool

```bash
cortex sync --smart
```

Instead of sending the same blob everywhere, Cortex can route:

- code and architecture context to Claude Code, Codex, Cursor, Copilot, Gemini, and Windsurf
- broader personal and professional context to ChatGPT, Claude, and Grok
- tighter conventions and preferences to coding assistants that benefit from short, high-signal instructions

MCP-capable tools do not have to wait for a stale file refresh. They can ask Cortex for their current routed slice live with `portability_context`.

### 5. Catch stale or conflicting context

```bash
cortex status
cortex audit
```

That lets you see:

- which tool has stale context
- which important facts have not been propagated yet
- where one tool still believes something that another tool has already outgrown

### 6. Build context from your digital footprint

```bash
cortex build --from package.json --from git-history --from github --sync --smart
```

You do not need to start with a chat export. Cortex can build useful AI context from things you already have:

- project manifests like `package.json`, `pyproject.toml`, or `Cargo.toml`
- git history
- local GitHub-style repositories
- resumes and profile docs

### 7. Switch platforms fast

```bash
cortex switch --from chatgpt-export.zip --to claude
```

Cortex extracts the identity graph from the source material, filters it, and generates a target-specific output instead of just dumping raw chat logs somewhere else.

## Supported Tools

### Direct local installs

These tools get written directly when a local file surface exists:

- Claude Code
- Codex
- Cursor
- Copilot
- Gemini
- Windsurf

### Live context via MCP

Any MCP-capable client can ask Cortex for its current routed slice live instead of relying only on files that may drift.

The portability MCP surface includes:

- `portability_context`
- `portability_scan`
- `portability_status`
- `portability_audit`

### Import-ready artifacts

These tools get honest, import-ready or paste-ready outputs:

- Claude
- ChatGPT
- Grok

The exact target model and file paths live in [docs/PORTABILITY.md](docs/PORTABILITY.md).

## Why This Is Better Than Manual Instructions

Without Cortex, the usual workflow is ugly:

1. copy the same project description into multiple tools
2. hand-edit `CLAUDE.md`, Cursor rules, Copilot instructions, and whatever else you use
3. forget to update one of them
4. get outdated or inconsistent AI advice later

With Cortex, you get:

- one source of truth for your portable context
- side-by-side visibility into what each tool knows
- smarter per-tool routing instead of one giant generic prompt
- live MCP context for agents that can query Cortex directly
- freshness checks instead of stale rule files
- cross-tool conflict detection instead of silent drift
- user-owned local storage instead of another hosted memory silo

## Real Use Cases

### Switch from one AI platform to another

Import a ChatGPT export, generate Claude-ready artifacts, and keep your coding tools in sync without starting from scratch.

### Keep your coding assistants aligned

Teach Claude Code, Codex, Cursor, Copilot, Gemini, and Windsurf about your stack, architecture, and conventions from one command.

### Bootstrap context with no export at all

Build context from your repos, manifests, and git history so your tools learn your real stack instead of waiting for you to type it again.

### Find stale or contradictory AI context

See which tools still believe old framework versions, old project names, or outdated database choices before they give you bad advice.

## Why Cortex Is Defensible

Portability is the front door, but Cortex is not just a thin export script.

Underneath the portability layer, Cortex still gives you:

- a local graph as the canonical source of truth
- immutable versioned commits
- branching, merge, rollback, and review flows
- blame and provenance
- governance and access control
- REST, SDK, MCP, and local UI surfaces

That matters because portability without control becomes another brittle sync layer. Cortex is trying to make portable AI context operable, not just copyable.

## Who It Is For

- developers who use multiple AI tools and hate re-explaining themselves
- teams that want portable, user-owned context instead of another hosted memory silo
- builders who want a local control plane for AI context
- power users who care about freshness, auditability, rollback, and source attribution once portability is in place

## Quick Command Map

```bash
# import from an export or existing graph
cortex portable chatgpt-export.zip --to all --project .

# audit what each tool knows
cortex scan

# teach Cortex once and propagate it
cortex remember "We use Vitest now"

# route the right context to the right tools
cortex sync --smart

# expose live portability context to MCP clients
cortex-mcp --config .cortex/config.toml

# show stale tools and missing facts
cortex status

# detect cross-tool drift
cortex audit

# build from repos, manifests, and git history
cortex build --from package.json --from git-history --from github --sync --smart

# switch from one platform to another
cortex switch --from chatgpt-export.zip --to claude
```

## Beta Status

Cortex is ready for self-hosted beta use by technical teams. It is not positioned as a hosted SaaS, and it is not pretending to be mass-market consumer software yet.

The intended posture is:

- keep storage user-owned
- run it locally or self-host it
- keep verified backups
- use scoped keys and namespace boundaries when you expose the API or MCP server

Relevant docs:

- [docs/PORTABILITY.md](docs/PORTABILITY.md)
- [docs/BETA_QUICKSTART.md](docs/BETA_QUICKSTART.md)
- [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md)
- [docs/OPERATIONS.md](docs/OPERATIONS.md)
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)
- [beta feedback template](.github/ISSUE_TEMPLATE/beta_feedback.md)

## Design Partners

If you are building with multiple AI tools today and you want a serious, user-owned portability layer, I would love feedback.

The best fit right now is:

- people using Claude Code, Cursor, Copilot, Codex, Gemini, ChatGPT, or Grok in real workflows
- teams that want one source of truth for AI context
- builders who care about portability first, and operability right after

Repo: [https://github.com/Junebugg1214/Cortex-AI](https://github.com/Junebugg1214/Cortex-AI)
