# Cortex — Your Portable AI Identity

**Own your AI memory. Take it everywhere.**

Cortex extracts your context from every AI platform you use — ChatGPT, Claude, Gemini, Perplexity — and every coding tool — Claude Code, Cursor, Copilot — merges it into a single knowledge graph, and lets you selectively push it back to any platform. Cryptographically signed. Version controlled. Zero external dependencies.

```bash
pip install cortex-identity

# Extract from ChatGPT, export to Claude
cortex chatgpt-export.zip --to claude -o ./output

# Visualize your knowledge graph
cortex viz context.json --output graph.html

# Launch the dashboard
cortex dashboard context.json
```

> **Nobody else builds user-owned portable AI identity.** Mem0, Letta, and built-in AI memories are agent memory — owned by the platform. Cortex is *your* memory, under *your* control.

---

## How It Works

```
Chat Exports (ChatGPT, Claude, Gemini, Perplexity, API logs)
  + Coding Sessions (Claude Code, Cursor, Copilot)
        |
   cortex.extract_memory      Parse exports, extract entities (declarative)
   cortex.coding              Parse coding sessions (behavioral)
        |
   CortexGraph                Nodes (entities) + Edges (relationships)
        |
   UPAI Protocol              Sign, version, control disclosure
        |
   Platform Adapters          Push selective views to Claude, Notion, etc.
        |
   Flywheel                   Auto-extract, auto-sync, dashboard
```

**Nodes are entities, not category items.** "Python" is ONE node with tags `[technical_expertise, domain_knowledge]` — not duplicated across categories. Edges capture typed relationships: `Python --applied_in--> Healthcare`.

---

## Quick Start

### Install

```bash
pip install cortex-identity
```

That's it. Zero dependencies — pure Python stdlib.

### Use

```bash
# Extract context from a chat export
cortex chatgpt-export.zip --to claude -o ./output

# Or extract to universal JSON first
cortex extract chatgpt-export.zip -o context.json

# Then export to any platform
cortex import context.json --to all -o ./output
```

### Optional Extras

```bash
pip install cortex-identity[crypto]   # Ed25519 signatures (PyNaCl)
pip install cortex-identity[fast]     # 10x faster graph layout (numpy)
pip install cortex-identity[full]     # Both
pip install cortex-identity[dev]      # + pytest for running tests
```

### From Source

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd chatbot-memory-skills
pip install -e .
```

### Requirements

- Python 3.10+ (macOS, Linux, Windows)
- No external packages required for core functionality

### Production Ready

v6.4 has been hardened for cross-platform use: atomic file saves prevent data corruption, paths with spaces are properly quoted, `sys.executable` ensures Windows compatibility, and all extraction errors surface to stderr for debugging.

---

## The Ten Layers

### 1. Graph Foundation

Everything is nodes and edges. Nodes have tags (not fixed categories), confidence scores, temporal metadata, and extensible properties. The graph is backward compatible — v4 flat-category JSON converts losslessly.

```bash
cortex query context.json --node "Python"
cortex query context.json --neighbors "Python"
cortex stats context.json
```

### 2. Temporal Engine

Every extraction snapshots each node's state. Cortex tracks how your identity evolves, detects contradictions ("said X in January, not-X in March"), and computes drift scores across time windows.

```bash
cortex timeline context.json --format html
cortex contradictions context.json --severity 0.5
cortex drift context.json --window 90
```

### 3. UPAI Protocol (Universal Portable AI Identity)

The breakthrough layer. Three capabilities:

- **Cryptographic signing** — SHA-256 integrity (always). Ed25519 signatures (with `pynacl`). Proves the graph is yours and untampered.
- **Selective disclosure** — Policies control what each platform sees. "Professional" shows job/skills. "Technical" shows your tech stack. "Minimal" shows almost nothing.
- **Version control** — Git-like commits for your identity. Log, diff, checkout, rollback.

```bash
# Initialize identity
cortex identity init --name "Your Name"

# Commit a version
cortex identity commit context.json -m "Added June ChatGPT export"

# View history
cortex identity log

# Compare versions
cortex identity diff v1 v2

# Push to Claude with professional disclosure policy
cortex sync claude --push --policy professional -o ./output
```

**Built-in disclosure policies:**

| Policy | What's Shared | Min Confidence |
|--------|---------------|----------------|
| `full` | Everything | 0.0 |
| `professional` | Identity, work, skills, priorities | 0.6 |
| `technical` | Tech stack, domain knowledge, priorities | 0.5 |
| `minimal` | Identity, communication preferences only | 0.8 |

### 4. Smart Edges

Automatic relationship discovery:

- **Pattern rules** — `technical_expertise` + `active_priorities` = `used_in` edge
- **Co-occurrence** — entities appearing together in messages get linked (PMI for large datasets, frequency thresholds for small)
- **Centrality** — identifies your most important nodes (degree centrality, PageRank for 200+ nodes)
- **Graph-aware dedup** — merges near-duplicates using 70% text similarity + 30% neighbor overlap

### 5. Query + Intelligence

Structured queries and proactive analysis:

```bash
# Find by category, confidence, relationships
cortex query context.json --category technical_expertise
cortex query context.json --strongest 10
cortex query context.json --isolated

# Shortest path between two nodes
cortex query context.json --path "Python" "Mayo Clinic"

# Connected components
cortex query context.json --components

# Gap analysis — what's missing from your graph?
cortex gaps context.json

# Weekly digest — what changed?
cortex digest context.json --previous last_week.json
```

### 6. Visualization + Flywheel

See your graph, keep it alive:

```bash
# Interactive HTML visualization (zoom, pan, hover, click)
cortex viz context.json --output graph.html

# Static SVG for documents
cortex viz context.json --output graph.svg --format svg

# Live dashboard with stats, gaps, components
cortex dashboard context.json --port 8420

# Auto-extract new exports dropped into a folder
cortex watch ~/exports/ --graph context.json

# Scheduled sync to platforms
cortex sync-schedule --config sync_config.json
```

### 7. Coding Tool Extraction

Extract identity from what you *actually do*, not just what you say. Coding sessions reveal your real tech stack, tools, and workflow through behavior:

```bash
# Auto-discover and extract from Claude Code sessions
cortex extract-coding --discover -o coding_context.json

# Filter by project name
cortex extract-coding --discover --project chatbot-memory

# Merge coding extraction with chatbot extraction
cortex extract-coding --discover --merge context.json -o context.json

# Enrich with project files (README, manifests, license)
cortex extract-coding --discover --enrich --stats

# Extract from a specific session file
cortex extract-coding ~/.claude/projects/*/session.jsonl
```

**What it extracts:**

| Signal | How | Example |
|--------|-----|---------|
| Languages | File extensions | Editing `.py` files -> Python |
| Frameworks | Config files | `package.json` -> Node.js |
| CLI tools | Bash commands | Running `pytest` -> Pytest |
| Projects | Working directory | `/home/user/myapp` -> myapp |
| Patterns | Tool sequence | Uses plan mode before coding |

**Project enrichment** (`--enrich`): Reads README, package manifests (package.json, pyproject.toml, Cargo.toml), and LICENSE files from project directories to extract project descriptions, metadata, and domain knowledge. Detects CI/CD and Docker presence.

Currently supports **Claude Code** (JSONL transcripts). Cursor and Copilot parsers planned.

### 8. Auto-Inject Context

Every new Claude Code session automatically gets your Cortex identity injected. Install once, context flows forever:

```bash
# Install the hook (one-time setup)
cortex context-hook install context.json

# Preview what gets injected
cortex context-hook test

# Export compact context manually
cortex context-export context.json --policy technical
```

The hook loads your graph, applies disclosure filtering, and injects a compact markdown summary (~300-800 chars) as a system message. Your AI always knows your tech stack, projects, and preferences.

### 9. Cross-Platform Context Writer

Write persistent Cortex identity to **every AI coding tool** with non-destructive section markers that preserve your existing rules:

```bash
# Write to all 6 platforms at once
cortex context-write graph.json --platforms all --project ~/myproject

# Write to specific platforms
cortex context-write graph.json --platforms cursor copilot windsurf

# Preview without writing
cortex context-write graph.json --platforms all --dry-run

# Auto-refresh when your graph updates
cortex context-write graph.json --platforms all --watch
```

**Supported platforms:**

| Platform | Config File | Scope |
|----------|------------|-------|
| Claude Code | `~/.claude/MEMORY.md` | Global |
| Claude Code (project) | `{project}/.claude/MEMORY.md` | Project |
| Cursor | `{project}/.cursor/rules/cortex.mdc` | Project |
| GitHub Copilot | `{project}/.github/copilot-instructions.md` | Project |
| Windsurf | `{project}/.windsurfrules` | Project |
| Gemini CLI | `{project}/GEMINI.md` | Project |

Uses `<!-- CORTEX:START -->` / `<!-- CORTEX:END -->` markers — your hand-written rules are never overwritten.

### 10. Continuous Extraction

Watch Claude Code sessions in real-time. Auto-extract behavioral signals as you code, merge into your graph, and optionally chain to cross-platform context refresh:

```bash
# Watch and auto-update graph
cortex extract-coding --watch -o coding_context.json

# Watch + auto-refresh context to all platforms
cortex extract-coding --watch -o ctx.json \
    --context-refresh claude-code cursor copilot

# Watch specific project only
cortex extract-coding --watch --project chatbot-memory -o ctx.json

# Custom interval and debounce
cortex extract-coding --watch --interval 15 --settle 10 -o ctx.json
```

**How it works:** Polls `~/.claude/projects/` for `*.jsonl` changes (mtime + size), debounces active writes (5s settle), extracts via the coding pipeline, and incrementally merges nodes by label (max confidence, sum mentions, union tags). Graph updates trigger an optional `on_update` callback for cross-platform refresh.

---

## Supported Platforms

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

---

## Extraction Categories

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

---

## Key Features

### PII Redaction

Strip sensitive data before extraction:

```bash
cortex chatgpt-export.zip --to claude --redact

# With custom patterns
cortex chatgpt-export.zip --to claude --redact --redact-patterns custom.json
```

Redacts: emails, phones, SSNs, credit cards, API keys, IP addresses, street addresses.

### Incremental Merge

Combine new exports without losing existing data:

```bash
cortex extract export1.json -o context.json
cortex extract export2.json --merge context.json -o context.json
```

### Conflict Detection

Automatically flags contradictions:

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

---

## Architecture

```
cortex-identity/                    # pip install cortex-identity
├── pyproject.toml                  # Package metadata + entry points
├── cortex/
│   ├── cli.py                  # CLI entry point (23 subcommands)
│   ├── extract_memory.py       # Extraction engine (~1400 LOC)
│   ├── import_memory.py        # Import/export engine (~1000 LOC)
│   ├── graph.py                # Node, Edge, CortexGraph (schema 6.0)
│   ├── compat.py               # v4 <-> v5 conversion
│   ├── temporal.py             # Snapshots, drift scoring
│   ├── contradictions.py       # Contradiction detection
│   ├── timeline.py             # Timeline views
│   ├── upai/
│   │   ├── identity.py         # UPAI identity, DID, Ed25519/HMAC signing
│   │   ├── disclosure.py       # Selective disclosure policies
│   │   └── versioning.py       # Git-like version control
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
│   ├── viz/                    # Visualization
│   ├── dashboard/              # Local web dashboard
│   └── sync/                   # File watcher + scheduled sync
├── migrate.py                  # Backward-compat stub → cortex.cli
├── cortex-hook.py              # Backward-compat stub → cortex._hook
└── tests/                      # 618 tests across 21 files
```

---

## CLI Reference

### Extract & Import

```bash
cortex <export> --to <platform> -o ./output    # One-step migrate
cortex extract <export> -o context.json         # Extract only
cortex import context.json --to <platform>      # Import only
cortex merge old.json new.json -o merged.json   # Merge contexts
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
cortex identity init --name <name>              # Create identity
cortex identity commit <graph> -m <message>     # Version commit
cortex identity log                             # Version history
cortex identity diff <v1> <v2>                  # Compare versions
cortex sync <platform> --push --policy <name>   # Push to platform
cortex sync <platform> --pull <file>            # Pull from platform
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

### Temporal Analysis

```bash
cortex timeline <graph> --format html           # Timeline view
cortex contradictions <graph> --severity 0.5    # Find conflicts
cortex drift <graph> --window 90                # Identity drift
```

---

## Competitive Landscape

| Capability | Cortex | Mem0 | Letta | ChatGPT Memory | Claude Memory |
|---|:-:|:-:|:-:|:-:|:-:|
| Knowledge Graph | Yes | Partial | No | No | No |
| **Portability (UPAI)** | **Yes** | No | No | No | No |
| **User-Owned** | **Yes** | No | No | No | No |
| **Temporal Tracking** | **Yes** | No | No | No | No |
| **Coding Tool Extraction** | **Yes** | No | No | No | No |
| **Auto-Inject Context** | **Yes** | No | No | No | No |
| **Cross-Platform Context** | **Yes (6)** | No | No | No | No |
| **Continuous Extraction** | **Yes** | No | No | No | No |
| Zero-Dep / Local-First | Yes | No | No | N/A | N/A |

---

## Version History

| Version | Milestone |
|---------|-----------|
| v6.4 | **pip packaging + continuous extraction + production hardening** — `pip install cortex-identity` with `cortex` CLI entry point; real-time session watching with debounce, incremental graph merge, cross-platform auto-refresh; hardened for production (atomic saves, path quoting, Windows compat, error visibility); 35 sys.path hacks eliminated |
| v6.3 | **Cross-platform context writer** — persistent context files for Claude Code, Cursor, Copilot, Windsurf, Gemini CLI with non-destructive section markers |
| v6.2 | **Auto-inject context** — SessionStart hook for Claude Code, compact context generation, install/uninstall CLI |
| v6.1 | **Coding tool extraction** — behavioral extraction from Claude Code sessions, project enrichment |
| v6.0 | Visualization, dashboard, file monitor, sync scheduler |
| v5.4 | Query engine, gap analysis, weekly digest |
| v5.3 | Smart edge extraction, co-occurrence, centrality, dedup |
| v5.2 | **UPAI Protocol** — cryptographic signing, selective disclosure, version control |
| v5.1 | Temporal snapshots, contradiction engine, drift scoring |
| v5.0 | Graph foundation — category-agnostic nodes, edges, v4 roundtrip |
| v4.3 | PII redaction |
| v4.2 | Typed relationships, conflict detection, incremental merge |
| v4.1 | Negation detection, preferences/constraints, Gemini/Perplexity support |
| v4.0 | Semantic dedup, time decay, Notion/Google Docs export |

---

## License

MIT License - See [LICENSE](LICENSE)

## Author

Created by [@Junebugg1214](https://github.com/Junebugg1214)
