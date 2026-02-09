# Cortex — Your Portable AI Identity

**Own your AI memory. Take it everywhere.**

Cortex extracts your context from every AI platform you use — ChatGPT, Claude, Gemini, Perplexity — and every coding tool — Claude Code, Cursor, Copilot — merges it into a single knowledge graph, and lets you selectively push it back to any platform. Cryptographically signed. Version controlled. Zero external dependencies.

```bash
# Extract from ChatGPT, export to Claude
python migrate.py chatgpt-export.zip --to claude -o ./output

# Visualize your knowledge graph
python migrate.py viz context.json --output graph.html

# Launch the dashboard
python migrate.py dashboard context.json
```

> **Nobody else builds user-owned portable AI identity.** Mem0, Letta, and built-in AI memories are agent memory — owned by the platform. Cortex is *your* memory, under *your* control.

---

## How It Works

```
Chat Exports (ChatGPT, Claude, Gemini, Perplexity, API logs)
  + Coding Sessions (Claude Code, Cursor, Copilot)
        |
   extract_memory.py          Parse exports, extract entities (declarative)
   cortex/coding.py           Parse coding sessions (behavioral)
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

```bash
git clone https://github.com/Junebugg1214/chatbot-memory-skills.git
cd chatbot-memory-skills

# Extract context from a chat export
python migrate.py chatgpt-export.zip --to claude -o ./output

# Or extract to universal JSON first
python migrate.py extract chatgpt-export.zip -o context.json

# Then export to any platform
python migrate.py import context.json --to all -o ./output
```

### Requirements

- Python 3.10+
- No external packages (stdlib only)
- Optional: `PyNaCl` for Ed25519 signatures (`pip install pynacl`)
- Optional: `numpy` for 10x faster graph layout (`pip install numpy`)

---

## The Seven Layers

### 1. Graph Foundation

Everything is nodes and edges. Nodes have tags (not fixed categories), confidence scores, temporal metadata, and extensible properties. The graph is backward compatible — v4 flat-category JSON converts losslessly.

```bash
python migrate.py query context.json --node "Python"
python migrate.py query context.json --neighbors "Python"
python migrate.py stats context.json
```

### 2. Temporal Engine

Every extraction snapshots each node's state. Cortex tracks how your identity evolves, detects contradictions ("said X in January, not-X in March"), and computes drift scores across time windows.

```bash
python migrate.py timeline context.json --format html
python migrate.py contradictions context.json --severity 0.5
python migrate.py drift context.json --window 90
```

### 3. UPAI Protocol (Universal Portable AI Identity)

The breakthrough layer. Three capabilities:

- **Cryptographic signing** — SHA-256 integrity (always). Ed25519 signatures (with `pynacl`). Proves the graph is yours and untampered.
- **Selective disclosure** — Policies control what each platform sees. "Professional" shows job/skills. "Technical" shows your tech stack. "Minimal" shows almost nothing.
- **Version control** — Git-like commits for your identity. Log, diff, checkout, rollback.

```bash
# Initialize identity
python migrate.py identity init --name "Your Name"

# Commit a version
python migrate.py identity commit context.json -m "Added June ChatGPT export"

# View history
python migrate.py identity log

# Compare versions
python migrate.py identity diff v1 v2

# Push to Claude with professional disclosure policy
python migrate.py sync claude --push --policy professional -o ./output
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
python migrate.py query context.json --category technical_expertise
python migrate.py query context.json --strongest 10
python migrate.py query context.json --isolated

# Shortest path between two nodes
python migrate.py query context.json --path "Python" "Mayo Clinic"

# Connected components
python migrate.py query context.json --components

# Gap analysis — what's missing from your graph?
python migrate.py gaps context.json

# Weekly digest — what changed?
python migrate.py digest context.json --previous last_week.json
```

### 6. Visualization + Flywheel

See your graph, keep it alive:

```bash
# Interactive HTML visualization (zoom, pan, hover, click)
python migrate.py viz context.json --output graph.html

# Static SVG for documents
python migrate.py viz context.json --output graph.svg --format svg

# Live dashboard with stats, gaps, components
python migrate.py dashboard context.json --port 8420

# Auto-extract new exports dropped into a folder
python migrate.py watch ~/exports/ --graph context.json

# Scheduled sync to platforms
python migrate.py sync-schedule --config sync_config.json
```

### 7. Coding Tool Extraction

Extract identity from what you *actually do*, not just what you say. Coding sessions reveal your real tech stack, tools, and workflow through behavior:

```bash
# Auto-discover and extract from Claude Code sessions
python migrate.py extract-coding --discover -o coding_context.json

# Filter by project name
python migrate.py extract-coding --discover --project chatbot-memory

# Merge coding extraction with chatbot extraction
python migrate.py extract-coding --discover --merge context.json -o context.json

# Extract from a specific session file
python migrate.py extract-coding ~/.claude/projects/*/session.jsonl
```

**What it extracts:**

| Signal | How | Example |
|--------|-----|---------|
| Languages | File extensions | Editing `.py` files -> Python |
| Frameworks | Config files | `package.json` -> Node.js |
| CLI tools | Bash commands | Running `pytest` -> Pytest |
| Projects | Working directory | `/home/user/myapp` -> myapp |
| Patterns | Tool sequence | Uses plan mode before coding |

Currently supports **Claude Code** (JSONL transcripts). Cursor and Copilot parsers planned.

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
python migrate.py chatgpt-export.zip --to claude --redact

# With custom patterns
python migrate.py chatgpt-export.zip --to claude --redact --redact-patterns custom.json
```

Redacts: emails, phones, SSNs, credit cards, API keys, IP addresses, street addresses.

### Incremental Merge

Combine new exports without losing existing data:

```bash
python migrate.py extract export1.json -o context.json
python migrate.py extract export2.json --merge context.json -o context.json
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
chatbot-memory-skills/
├── cortex/
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
│   ├── viz/
│   │   ├── layout.py           # Fruchterman-Reingold layout
│   │   └── renderer.py         # HTML (interactive) + SVG (static)
│   ├── dashboard/
│   │   └── server.py           # Local web dashboard
│   └── sync/
│       ├── monitor.py          # File watcher auto-extraction
│       └── scheduler.py        # Periodic platform sync
├── extract_memory.py           # Extraction engine
├── import_memory.py            # Import/export engine
├── migrate.py                  # CLI (20 subcommands)
└── tests/                      # 493 tests across 18 files
```

---

## CLI Reference

### Extract & Import

```bash
python migrate.py <export> --to <platform> -o ./output    # One-step migrate
python migrate.py extract <export> -o context.json         # Extract only
python migrate.py import context.json --to <platform>      # Import only
python migrate.py merge old.json new.json -o merged.json   # Merge contexts
```

### Query & Intelligence

```bash
python migrate.py query <graph> --node <label>             # Find node
python migrate.py query <graph> --neighbors <label>        # Find neighbors
python migrate.py query <graph> --category <tag>           # Filter by tag
python migrate.py query <graph> --path <from> <to>         # Shortest path
python migrate.py query <graph> --strongest <n>            # Top N nodes
python migrate.py query <graph> --weakest <n>              # Bottom N nodes
python migrate.py query <graph> --isolated                 # Unconnected nodes
python migrate.py query <graph> --components               # Connected clusters
python migrate.py gaps <graph>                             # Gap analysis
python migrate.py digest <graph> --previous <old>          # Weekly digest
python migrate.py stats <graph>                            # Graph statistics
```

### Identity & Sync

```bash
python migrate.py identity init --name <name>              # Create identity
python migrate.py identity commit <graph> -m <message>     # Version commit
python migrate.py identity log                             # Version history
python migrate.py identity diff <v1> <v2>                  # Compare versions
python migrate.py sync <platform> --push --policy <name>   # Push to platform
python migrate.py sync <platform> --pull <file>            # Pull from platform
```

### Visualization & Flywheel

```bash
python migrate.py viz <graph> --output graph.html          # Interactive HTML
python migrate.py viz <graph> --output graph.svg --format svg  # Static SVG
python migrate.py dashboard <graph> --port 8420            # Web dashboard
python migrate.py watch <dir> --graph <graph>              # Auto-extract
python migrate.py sync-schedule --config <config.json>     # Scheduled sync
```

### Coding Tool Extraction

```bash
python migrate.py extract-coding <session.jsonl>           # From specific file
python migrate.py extract-coding --discover                # Auto-find sessions
python migrate.py extract-coding --discover -p <project>   # Filter by project
python migrate.py extract-coding --discover -m <context>   # Merge with existing
python migrate.py extract-coding --discover --stats        # Show session stats
```

### Temporal Analysis

```bash
python migrate.py timeline <graph> --format html           # Timeline view
python migrate.py contradictions <graph> --severity 0.5    # Find conflicts
python migrate.py drift <graph> --window 90                # Identity drift
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
| Zero-Dep / Local-First | Yes | No | No | N/A | N/A |

---

## Version History

| Version | Milestone |
|---------|-----------|
| v6.1 | **Coding tool extraction** — behavioral extraction from Claude Code sessions |
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
