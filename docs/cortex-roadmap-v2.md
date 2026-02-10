# Cortex Roadmap v2 — COMPLETE

## Context

This is the revised Cortex roadmap for chatbot-memory-skills, incorporating all 12 issues identified during the staff-engineer review. **All 7 phases are now complete (v6.4.0, 618 passing tests).** The three biggest changes were:

1. **Node identity model redesigned** — category-agnostic nodes with tags (not category-scoped IDs)
2. **Phases reordered** — UPAI (the breakthrough) shipped as Phase 3 instead of Phase 5
3. **Algorithm choices right-sized** — designed for realistic 50-200 node graphs, not fantasy scale

---

## Architecture Overview

```
Phase 1 (v5.0)  →  Phase 2 (v5.1)  →  Phase 3 (v5.2)  →  Phase 4 (v5.3)  →  Phase 5 (v5.4)  →  Phase 6 (v6.0)  →  Phase 7 (v6.1)
Graph Foundation    Temporal Engine     UPAI Protocol       Smart Edges         Query + Intel       Viz + Flywheel      Coding Extraction
  [DONE]              [DONE]           [DONE] ***            [DONE]              [DONE]              [DONE]              [DONE]
                                       BREAKTHROUGH
```

**Why reorder:** UPAI (portable AI identity) is the breakthrough. It depends on Phase 1 (graph) and Phase 2 (temporal), but NOT on smart edges or query intelligence. This gets the differentiator out 2 phases sooner.

**Design Constraints (all met):**
- Zero external dependencies for core (stdlib only, Python 3.10+)
- Optional dependency tiers: `cortex[crypto]`, `cortex[fast]`, `cortex[full]`
- Backward compatible: v4 JSON always works, existing tests never break
- Offline/local first: no cloud dependency
- Each phase independently shippable
- **618 tests across 21 test files, all passing**

---

## Phase 1: Graph Foundation (v5.0) — COMPLETE

**Objective:** Introduce a Node/Edge graph model underneath the existing flat categories. All existing tests + CLI commands continue to work identically.

### Critical Design Decision: Category-Agnostic Nodes

Nodes are **entities**, not category-scoped items. "Python" is ONE node regardless of whether it appears in `technical_expertise`, `domain_knowledge`, or `active_priorities`.

```python
@dataclass
class Node:
    id: str              # deterministic hash of normalized_label (NOT category-scoped)
    label: str           # "Python", "Marc Saint-Jour"
    tags: list[str]      # ["technical_expertise", "domain_knowledge"] — multi-category
    confidence: float    # highest confidence across all appearances
    properties: dict     # extensible metadata bucket
    brief: str = ""
    full_description: str = ""
    mention_count: int = 1
    extraction_method: str = "mentioned"
    metrics: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    source_quotes: list[str] = field(default_factory=list)
    first_seen: str = ""   # ISO-8601
    last_seen: str = ""    # ISO-8601
    relationship_type: str = ""  # for backward compat with v4 typed relationships

@dataclass
class Edge:
    id: str              # hash of (source_id, target_id, relation)
    source_id: str
    target_id: str
    relation: str        # "uses", "works_at", "competes_with", "co_mentioned", etc.
    confidence: float
    properties: dict = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""

@dataclass
class CortexGraph:
    nodes: dict[str, Node]       # node_id → Node
    edges: dict[str, Edge]       # edge_id → Edge
    schema_version: str = "5.0"
    meta: dict = field(default_factory=dict)
```

### v5 JSON Schema

```json
{
  "schema_version": "5.0",
  "meta": {
    "generated_at": "ISO-8601",
    "method": "aggressive_extraction_v5",
    "features": ["graph_model", "multi_tag_nodes", "semantic_dedup", "time_decay", "typed_relationships"],
    "node_count": 85,
    "edge_count": 42
  },
  "graph": {
    "nodes": {
      "a1b2c3": {
        "id": "a1b2c3",
        "label": "Python",
        "tags": ["technical_expertise", "domain_knowledge"],
        "confidence": 0.85,
        "properties": {},
        "brief": "Programming language",
        "full_description": "Primary programming language used for data analysis",
        "mention_count": 8,
        "extraction_method": "self_reference",
        "metrics": [],
        "timeline": ["current"],
        "source_quotes": ["I use Python daily", "my Python scripts"],
        "first_seen": "2025-01-01T00:00:00Z",
        "last_seen": "2025-02-07T00:00:00Z",
        "relationship_type": ""
      }
    },
    "edges": {
      "d4e5f6": {
        "id": "d4e5f6",
        "source_id": "a1b2c3",
        "target_id": "g7h8i9",
        "relation": "used_in",
        "confidence": 0.7,
        "properties": {},
        "first_seen": "2025-01-15T00:00:00Z",
        "last_seen": "2025-02-01T00:00:00Z"
      }
    }
  },
  "categories": {
    "technical_expertise": [
      {
        "topic": "Python",
        "brief": "Programming language",
        "confidence": 0.85,
        "mention_count": 8,
        "_node_id": "a1b2c3"
      }
    ]
  }
}
```

The `categories` block is **computed from the graph** for v4 backward compatibility. v4 consumers read `categories` and ignore `graph`. The `_node_id` field lets v5-aware consumers cross-reference.

### v4 ↔ v5 Conversion Rules

**v4 → v5 (upgrade):**
1. Each `ExtractedTopic` → 1 `Node`
2. Node ID = `sha256(normalize(label))[:12]` — if collision, append category
3. If same normalized label exists across categories → **merge into single node** with multiple tags
4. `topic.relationships` string list → resolve each string against existing node labels:
   - Match found → create Edge (source=this_node, target=matched_node, relation=topic.relationship_type or "related_to")
   - No match → create stub Node (confidence=0.3, tag=["mentions"]) + Edge
5. `topic.relationship_type` → Edge.relation field
6. All other ExtractedTopic fields map 1:1 to Node fields

**v5 → v4 (downgrade):**
1. For each Node, determine primary tag using CATEGORY_ORDER (first match wins)
2. Node → ExtractedTopic in that primary category
3. If Node has multiple tags, it appears in primary category only (lossy)
4. **Edges are LOST** — this is a documented, accepted limitation
5. Node.tags stored in properties["_original_tags"] for potential re-upgrade

**Roundtrip guarantees:**
- `v4 → v5 → v4` = **identical** (no data created that can't round-trip)
- `v5 → v4 → v5` = **lossy** (edges lost, multi-tag collapsed to primary)

### New Files

- `cortex/__init__.py`
- `cortex/graph.py` — Node, Edge, CortexGraph dataclasses + methods
- `cortex/compat.py` — `upgrade_v4_to_v5()`, `downgrade_v5_to_v4()`, roundtrip utilities
- `tests/test_graph.py` — Node/Edge CRUD, graph operations, v4↔v5 conversion, roundtrip tests

### Modify

- `extract_memory.py` — add `to_graph()` on ExtractionContext
- `import_memory.py` — `NormalizedContext.load()` detects v5 schema, converts via compat layer
- `migrate.py` — add `--schema v5` flag, add `query` subcommand (basic node/neighbor lookup)

### CortexGraph Methods

```python
class CortexGraph:
    # CRUD
    def add_node(self, node: Node) -> str
    def add_edge(self, edge: Edge) -> str
    def get_node(self, node_id: str) -> Node | None
    def get_edge(self, edge_id: str) -> Edge | None
    def remove_node(self, node_id: str) -> bool    # also removes connected edges
    def remove_edge(self, edge_id: str) -> bool

    # Query
    def find_nodes(self, label: str = None, tag: str = None, min_confidence: float = 0.0) -> list[Node]
    def get_neighbors(self, node_id: str, relation: str = None) -> list[tuple[Edge, Node]]
    def get_edges_for(self, node_id: str) -> list[Edge]

    # Merge
    def merge_nodes(self, node_id_a: str, node_id_b: str) -> Node

    # Export
    def to_v4_categories(self) -> dict
    def to_v5_json(self) -> dict
    def export_v4(self) -> dict
    def export_v5(self) -> dict

    # Stats
    def stats(self) -> dict
```

### New CLI

```bash
python migrate.py export.zip --to claude --schema v5
python migrate.py query context.json --node "Python"
python migrate.py query context.json --neighbors "Python"
python migrate.py stats context.json
```

### Tests

- All existing tests pass unchanged
- New: Node/Edge CRUD, find_nodes, get_neighbors, merge_nodes
- New: v4→v5 upgrade with label dedup across categories
- New: v5→v4 downgrade with primary tag selection
- New: v4→v5→v4 roundtrip = identical
- New: relationship string resolution to edges
- New: stub node creation for unresolved relationships

---

## Phase 2: Temporal Evolution + Contradiction Engine (v5.1) — COMPLETE

**Objective:** Track how nodes evolve over time via snapshots. Detect contradictions across the entire graph. Prerequisite for UPAI's version control.

### Snapshot Per Extraction

Snapshots are created on every extraction or merge. They are lightweight.

```python
@dataclass
class Snapshot:
    timestamp: str           # ISO-8601
    source: str              # "extraction", "merge", "manual"
    confidence: float        # node's confidence at this point
    tags: list[str]          # node's tags at this point
    properties_hash: str     # sha256 of sorted properties dict
    description_hash: str    # sha256 of full_description

@dataclass
class TemporalNode(Node):
    snapshots: list[Snapshot] = field(default_factory=list)
```

### Contradiction Engine

```python
@dataclass
class Contradiction:
    type: str            # "negation_conflict", "temporal_flip", "source_conflict", "tag_conflict"
    node_ids: list[str]
    severity: float      # 0.0-1.0
    description: str
    detected_at: str
    resolution: str      # "prefer_newer", "prefer_higher_confidence", "needs_review"
```

**Contradiction types:**
1. **negation_conflict** — same entity in positive tag + negations tag
2. **temporal_flip** — confidence changed direction ≥ 2 times across ≥ 3 snapshots. **Requires ≥ 3 snapshots.** Outputs "insufficient data" otherwise.
3. **source_conflict** — same node from different source files with description_hash mismatch
4. **tag_conflict** — node moved between contradictory tags over time

### Identity Drift Score

```
drift(graph_t1, graph_t2) = 1.0 - weighted_jaccard(nodes_t1, nodes_t2)

Category weights: identity: 3.0, values: 2.0, professional_context: 2.0, everything else: 1.0
Requires: ≥ 2 graph snapshots separated by ≥ 7 days
```

### New Files
- `cortex/temporal.py` — Snapshot, TemporalNode, drift scoring
- `cortex/contradictions.py` — ContradictionEngine (4 types)
- `cortex/timeline.py` — chronological event generation, markdown/HTML
- `tests/test_temporal.py`, `tests/test_contradictions.py`, `tests/test_timeline.py`

### Modify
- `cortex/graph.py` — TemporalNode, `graph_at(timestamp)`, `create_snapshot()`
- `extract_memory.py` — calls `create_snapshot()` after extraction
- `migrate.py` — subcommands: `timeline`, `contradictions`, `drift`

### New CLI

```bash
python migrate.py timeline context.json --from 2025-01-01 --format html
python migrate.py contradictions context.json --severity 0.5
python migrate.py drift context.json --window 90
```

---

## Phase 3: Universal Portable AI Identity Protocol — UPAI (v5.2) — COMPLETE

***THE BREAKTHROUGH — Nobody else is building this.***

**Objective:** Define and implement the UPAI protocol. Cryptographic integrity + ownership, selective disclosure, version control, file-based platform adapters, .well-known discoverability.

### Threat Model

| Concern | Mechanism | Requirement |
|---------|-----------|-------------|
| **Integrity** — data not tampered | SHA-256 hash of graph | stdlib (always available) |
| **Ownership** — I created this | Ed25519 signature | `cortex[crypto]` optional dep |
| **Authenticity** — verifiable by third parties | Public key + .well-known or signed file exchange | Requires key distribution |
| **Selective disclosure** — platform X sees subset Y | Disclosure policies filter graph before export | stdlib |

### Selective Disclosure

```python
@dataclass
class DisclosurePolicy:
    name: str                    # "professional", "technical", "full", "minimal"
    include_tags: list[str]      # tags to include (empty = all)
    exclude_tags: list[str]      # tags to exclude
    min_confidence: float        # confidence floor
    redact_properties: list[str] # property keys to strip
    max_nodes: int = 0           # 0 = unlimited

POLICIES = {
    "full": DisclosurePolicy(name="full", include_tags=[], exclude_tags=[], min_confidence=0.0),
    "professional": DisclosurePolicy(
        name="professional",
        include_tags=["identity", "professional_context", "business_context",
                      "technical_expertise", "active_priorities"],
        exclude_tags=["negations", "correction_history"],
        min_confidence=0.6
    ),
    "technical": DisclosurePolicy(
        name="technical",
        include_tags=["technical_expertise", "domain_knowledge", "active_priorities"],
        exclude_tags=[],
        min_confidence=0.5
    ),
    "minimal": DisclosurePolicy(
        name="minimal",
        include_tags=["identity", "communication_preferences"],
        exclude_tags=[],
        min_confidence=0.8
    )
}
```

### Version Control (Git-Like)

```python
@dataclass
class ContextVersion:
    version_id: str        # sha256 of graph content hash
    parent_id: str | None  # previous version (None for initial)
    timestamp: str
    message: str           # commit message
    graph_hash: str
    signature: str | None  # Ed25519 signature (if crypto available)
    snapshot: dict         # full graph JSON at this version
```

Full graph snapshots per commit (~50-100KB each). Delta optimization deferred to v6.0.

### Platform Adapters (File-Based I/O)

```python
class PlatformAdapter(ABC):
    @abstractmethod
    def push(self, graph: CortexGraph, policy: DisclosurePolicy) -> list[Path]:
        """Generate platform-specific files."""
    @abstractmethod
    def pull(self, file_path: Path) -> CortexGraph:
        """Parse platform export file back into a graph."""
    @abstractmethod
    def diff(self, local: CortexGraph, remote_file: Path) -> dict:
        """Compare local graph against platform export."""
```

| Adapter | Push | Pull | Notes |
|---------|------|------|-------|
| ClaudeAdapter | preferences.txt + memories.json | Parse memory_user_edits | Refactors existing exports |
| SystemPromptAdapter | system_prompt.txt | Parse XML system prompt | New pull |
| NotionAdapter | page.md + database.json | N/A (future) | Existing export |
| GDocsAdapter | google_docs.html | N/A (future) | Existing export |

**Push = generate files. Pull = parse exports. Live API sync = future.**

### Building on W3C Standards

Conceptual alignment (not full compliance):
- Node identity ← inspired by W3C DID structure
- Selective disclosure ← inspired by W3C Verifiable Credentials
- Integrity proofs ← compatible with VC Data Integrity spec
- Key format ← Ed25519 (same as DID:key method)

### Distribution

- `.well-known/ai-context.json` — for users with websites
- **Signed .cortex file** — portable, email-able, verifiable
- **Inline JSON in system prompt** — embed selective context directly

### Optional Dependency: cortex[crypto]

```toml
[project.optional-dependencies]
crypto = ["PyNaCl>=1.5.0"]
```

Without: SHA-256 integrity, HMAC-SHA256 basic ownership.
With: Ed25519 signatures, public key generation, third-party verification.

### New Files
- `cortex/upai/schema.py` — UPAIIdentity, DisclosurePolicy, ContextVersion
- `cortex/upai/crypto.py` — integrity hash, optional Ed25519
- `cortex/upai/versioning.py` — commit, log, diff, checkout, rollback
- `cortex/upai/wellknown.py` — .well-known + signed .cortex files
- `cortex/adapters/base.py` — PlatformAdapter ABC
- `cortex/adapters/claude_adapter.py`, `system_prompt_adapter.py`, `notion_adapter.py`, `gdocs_adapter.py`
- `tests/test_upai_schema.py`, `test_crypto.py`, `test_versioning.py`, `test_adapters.py`, `test_wellknown.py`

### Modify
- `import_memory.py` — export functions wrapped by adapters (direct calls still work)
- `migrate.py` — subcommand groups: `identity`, `sync`, `wellknown`

### New CLI

```bash
# Identity management
python migrate.py identity init --name "Marc Saint-Jour"
python migrate.py identity commit context.json -m "Added June ChatGPT export"
python migrate.py identity log
python migrate.py identity diff v1 v2

# Platform sync (file-based)
python migrate.py sync claude --push --policy professional -o ./output
python migrate.py sync claude --pull claude_memories.json
python migrate.py sync claude --diff claude_memories.json

# Distribution
python migrate.py wellknown context.json --policy professional -o .well-known/
python migrate.py export-signed context.json --policy technical -o identity.cortex
```

---

## Phase 4: Smart Edge Extraction (v5.3) — COMPLETE

**Objective:** Extract typed edges during extraction. Discover implicit relationships. Graph-aware dedup. Right-sized algorithms for 50-200 node graphs.

### Edge Extraction (Pattern-Based)

```python
@dataclass
class ExtractionRule:
    source_tag: str
    target_tag: str
    relation: str
    confidence: float

CATEGORY_PAIR_RULES = [
    ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6),
    ExtractionRule("identity", "business_context", "works_at", 0.7),
    ExtractionRule("identity", "professional_context", "holds_role", 0.7),
    ExtractionRule("relationships", "business_context", "associated_with", 0.5),
    ExtractionRule("technical_expertise", "domain_knowledge", "applied_in", 0.5),
    ExtractionRule("business_context", "market_context", "competes_in", 0.5),
    ExtractionRule("values", "active_priorities", "motivated_by", 0.4),
    ExtractionRule("constraints", "active_priorities", "constrained_by", 0.5),
]
```

**Fallback:** Nodes in same message within 200 chars → `co_mentioned` edge at 0.3 confidence.

### Co-Occurrence (Tiered by Data Size)

```python
def discover_edges(messages, nodes):
    if len(messages) >= 500:    # PMI (statistically reliable)
        edges = pmi_edges(counts, threshold=2.0, min_count=3)
    elif len(messages) >= 100:  # Frequency with minimum threshold
        edges = frequency_edges(counts, min_count=3, min_ratio=0.02)
    else:                       # Strict threshold only
        edges = frequency_edges(counts, min_count=3, min_ratio=0.05)
```

**Minimum co-occurrence count = 3 always required.**

### Centrality (Right-Sized)

```python
def compute_centrality(graph):
    if len(graph.nodes) >= 200:
        return compute_pagerank(graph, damping=0.85, iterations=100)
    else:
        return compute_degree_centrality(graph)
```

Confidence boost: up to +0.1 for top-decile nodes. Only if ≥ 20 nodes.

### Graph-Aware Dedup

```
similarity = 0.7 * text_similarity + 0.3 * neighbor_overlap
threshold = 0.80
```

### Optional LLM-Assisted

```bash
python migrate.py export.zip --to claude --discover-edges          # pattern-based
python migrate.py export.zip --to claude --discover-edges --llm    # LLM-assisted
```

### New Files
- `cortex/edge_extraction.py`, `cortex/cooccurrence.py`, `cortex/dedup.py`, `cortex/centrality.py`
- `tests/test_edge_extraction.py`, `tests/test_cooccurrence.py`, `tests/test_dedup.py`

### Modify
- `extract_memory.py` — optional EdgeExtractor, yields (Node, Edge) tuples
- `cortex/graph.py` — centrality methods
- `migrate.py` — `--discover-edges`, `--llm`, `stats`

---

## Phase 5: Query Engine + Intelligence Layer (v5.4) — COMPLETE

**Objective:** Structured query interface + proactive intelligence. All computed locally via graph traversal.

### Structured Query Interface

```python
class QueryEngine:
    def query_category(self, tag: str) -> list[Node]
    def query_path(self, from_label: str, to_label: str) -> list[list[Node]]
    def query_changed(self, since: str) -> dict
    def query_related(self, label: str, depth: int = 2) -> list[Node]
    def query_strongest(self, n: int = 10) -> list[Node]
    def query_weakest(self, n: int = 10) -> list[Node]
```

NL syntactic sugar (pattern-matched, limited):
- `"what are my [tag]"` → `query_category(tag)`
- `"how does X relate to Y"` → `query_path(X, Y)`
- `"what changed since [date]"` → `query_changed(date)`

Unrecognized → "Query not recognized. Use `--help` for supported syntax."

### Gap Analysis (Structured)

```python
class GapAnalyzer:
    def category_gaps(self, graph) -> list[dict]      # 0 nodes in a category
    def confidence_gaps(self, graph) -> list[dict]     # priorities < 0.6
    def relationship_gaps(self, graph) -> list[dict]   # 5 competitors, 0 investors
    def isolated_nodes(self, graph) -> list[Node]      # 0 edges
    def stale_nodes(self, graph, days=180) -> list[Node]  # not mentioned recently
```

### Weekly Digest

```python
class InsightGenerator:
    def digest(self, current, previous) -> dict:
        # new_nodes, removed_nodes, confidence_changes > 0.2,
        # new_edges, new_contradictions, drift_score, gaps
```

### Graph Algorithms
- `shortest_path()` — BFS
- `connected_components()` — union-find
- `betweenness_centrality()` — only for ≥ 50 nodes

### New Files
- `cortex/query.py`, `cortex/intelligence.py`
- `tests/test_query.py`, `tests/test_intelligence.py`

### New CLI

```bash
python migrate.py query context.json --category technical_expertise
python migrate.py query context.json --path "Python" "Mayo Clinic"
python migrate.py query context.json --changed-since 2025-01-01
python migrate.py query context.json --strongest 10
python migrate.py query context.json --isolated
python migrate.py gaps context.json
python migrate.py insights context.json
python migrate.py digest context.json --previous last_week.json
```

---

## Phase 6: Visualization + Flywheel (v6.0) — COMPLETE

**Objective:** Graph visualization, local web dashboard, auto-extraction, scheduled sync. The complete flywheel.

### Visualization

Fruchterman-Reingold in pure Python with optional numpy fast path (~10x). Mitigated by caching + progress indicator + 200 node default limit.

```bash
python migrate.py viz context.json --output graph.html
python migrate.py viz context.json --output graph.svg --max-nodes 100
```

### Dashboard

stdlib `http.server` + AJAX polling (5s). No WebSocket (would need deps).

```bash
python migrate.py dashboard context.json --port 8420
```

### Auto-Extraction

`os.stat()` polling (30s) on watched directory.

```bash
python migrate.py watch ~/exports/ --graph context.json --interval 30
```

### Scheduled Sync

`threading.Timer` for periodic file-based platform sync.

```bash
python migrate.py sync-schedule --config sync_config.json
```

### Optional Dependency: cortex[fast]

```toml
[project.optional-dependencies]
fast = ["numpy>=1.24.0"]
```

10x faster FR layout with numpy.

### Files
- `cortex/viz/layout.py` — Fruchterman-Reingold layout + caching + numpy fast path
- `cortex/viz/renderer.py` — Interactive HTML (Canvas 2D) + static SVG export
- `cortex/dashboard/server.py` — stdlib HTTP server + AJAX dashboard
- `cortex/sync/monitor.py` — os.stat() file polling auto-extraction
- `cortex/sync/scheduler.py` — threading.Timer periodic platform sync
- `tests/test_viz.py`, `tests/test_dashboard.py`, `tests/test_monitor.py`, `tests/test_scheduler.py`

---

## Phase 7: Coding Tool Extraction (v6.1) — COMPLETE

**Objective:** Extract identity signals from coding tool sessions (Claude Code, Cursor, Copilot) via behavioral analysis — files edited, tools run, commands executed, patterns followed. Complements existing declarative extraction from chatbot conversations.

### Behavioral vs Declarative Extraction

Chatbot extraction finds **declarative** signals: "I use Python", "My name is Marc". Coding session extraction finds **behavioral** signals: editing `.py` files, running `pytest`, using `git`. Both feed into the same CortexGraph.

### Signals Extracted

| Signal | Source | Maps To |
|--------|--------|---------|
| Languages/frameworks | File extensions (.py, .ts, .rs) | `technical_expertise` |
| CLI tools | Bash commands (pytest, git, docker) | `technical_expertise` |
| Active projects | Working directory (cwd) | `active_priorities` |
| Coding patterns | Plan mode, test-first, iteration style | `user_preferences` |
| Config files | package.json, pyproject.toml, Dockerfile | `technical_expertise` |

### Project Enrichment (`--enrich`)

Opt-in flag reads project files from disk to enrich extraction with project descriptions, metadata, and domain knowledge:

| Source | What's Extracted |
|--------|-----------------|
| README.md/.rst/.txt | First meaningful paragraph as project description |
| package.json | name, description, license, keywords, language |
| pyproject.toml | name, description, license |
| Cargo.toml | name, description, license |
| setup.cfg | name, description, license |
| LICENSE | License type (MIT, Apache-2.0, GPL, BSD, ISC) |
| .github/workflows/ | CI/CD presence |
| Dockerfile/docker-compose | Docker presence |

Enriched projects produce richer `active_priorities` nodes (with description in brief, metadata in full_description) and new `domain_knowledge` nodes for project purpose.

### CLI

```bash
python migrate.py extract-coding session.jsonl -o context.json
python migrate.py extract-coding --discover --project chatbot-memory
python migrate.py extract-coding --discover --merge context.json -o context.json
python migrate.py extract-coding --discover --enrich --stats
```

### Files
- `cortex/coding.py` — CodingSession parser, ProjectMetadata, enrich_project(), tech/tool/pattern extractors, session-to-v4 converter, multi-session aggregation, auto-discovery
- `tests/test_coding.py` — 74 tests covering detection, parsing, extraction, aggregation, enrichment, integration

### Modified
- `extract_memory.py` — Claude Code JSONL auto-detection in `load_file()`
- `migrate.py` — `extract-coding` subcommand with `--enrich` flag

### Auto-Inject Context Hook (v6.2)

Automatically injects your Cortex identity into every new Claude Code session via a SessionStart hook. Zero manual effort — your AI always knows who you are.

**How it works:**
1. `cortex-hook.py` is registered as a Claude Code SessionStart hook
2. On each new session, the hook loads your Cortex graph
3. Applies a disclosure policy (default: `technical`) to filter context
4. Formats a compact markdown summary (~300-800 chars)
5. Returns it as `additionalContext` — injected as a system message

```bash
# Install the hook (one-time)
python migrate.py context-hook install context.json --policy technical

# Preview what gets injected
python migrate.py context-hook test

# Check installation status
python migrate.py context-hook status

# One-shot compact export (for manual use)
python migrate.py context-export context.json
```

**Example injected context:**
```
## Your Cortex Context

**Tech Stack:** Python (0.9), Git (0.9), Pytest (0.8), GitHub CLI (0.8)
**Projects:** chatbot-memory-skills — Own your AI memory. Take it everywhere.
**Domain:** AI memory, knowledge graphs, portable identity
**Preferences:** Plans before coding, writes tests
```

#### Files
- `cortex/hooks.py` — HookConfig, generate_compact_context(), install/uninstall/status, handle_session_start()
- `cortex-hook.py` — Standalone hook entry point for Claude Code
- `tests/test_hooks.py` — 35 tests covering config, graph loading, formatting, session handling, install/uninstall
- `migrate.py` — `context-hook` and `context-export` subcommands

### Cross-Platform Context Writer (v6.3)

Persistent context files across all major AI coding tools. One command writes your Cortex identity to every platform's config file using non-destructive section markers that preserve user content.

**Supported platforms:**

| Platform | Config File | Scope | Format |
|----------|------------|-------|--------|
| `claude-code` | `~/.claude/MEMORY.md` | Global | Markdown with markers |
| `claude-code-project` | `{project}/.claude/MEMORY.md` | Project | Markdown with markers |
| `cursor` | `{project}/.cursor/rules/cortex.mdc` | Project | .mdc with YAML frontmatter |
| `copilot` | `{project}/.github/copilot-instructions.md` | Project | Markdown with markers |
| `windsurf` | `{project}/.windsurfrules` | Project | Markdown with markers |
| `gemini-cli` | `{project}/GEMINI.md` | Project | Markdown with markers |

**Non-destructive write strategy:** All writes use `<!-- CORTEX:START -->` / `<!-- CORTEX:END -->` section markers:
- File has markers → replace content between them (update in-place)
- File exists, no markers → append marked section at end
- File doesn't exist → create with marked section only

User's hand-written rules are never overwritten.

```bash
# Write to all coding tools for a project
python migrate.py context-write graph.json --platforms all --project ~/myproject

# Write to specific platforms
python migrate.py context-write graph.json --platforms cursor copilot

# Preview without writing
python migrate.py context-write graph.json --platforms all --dry-run

# Auto-refresh when graph updates
python migrate.py context-write graph.json --platforms all --watch --interval 30

# Override disclosure policy
python migrate.py context-write graph.json --platforms all --policy professional
```

#### Files
- `cortex/context.py` — PlatformTarget registry, CONTEXT_TARGETS, write_context(), _write_non_destructive(), watch_and_refresh()
- `tests/test_context.py` — 30 tests covering non-destructive writes, platform formatting, path resolution, idempotency, CLI integration
- `migrate.py` — `context-write` subcommand

### Continuous Extraction (v6.4)

Watch `~/.claude/projects/` for new/modified Claude Code session files in real-time. Automatically extracts behavioral signals, incrementally merges into the graph, and optionally chains to `context-write` for cross-platform auto-refresh.

**How it works:**
1. `CodingSessionWatcher` polls `~/.claude/projects/` recursively for `*.jsonl` files
2. Detects changes by comparing mtime + file size against tracked state
3. Two-phase debounce: waits `settle_seconds` (default 5s) of inactivity before processing — prevents thrashing on active sessions
4. Extracts via the existing coding pipeline: `load → parse → enrich → session_to_context → upgrade_v4_to_v5`
5. Incrementally merges into the graph: nodes by label (max confidence, sum mentions, union tags), edges if endpoints exist
6. Saves graph and fires `on_update` callback → optional `write_context()` for cross-platform refresh

```bash
# Watch and auto-update graph
python migrate.py extract-coding --watch -o coding_context.json

# Watch + auto-refresh context to all platforms
python migrate.py extract-coding --watch -o ctx.json \
    --context-refresh claude-code cursor copilot

# Watch specific project only
python migrate.py extract-coding --watch --project chatbot-memory -o ctx.json

# Custom interval and debounce
python migrate.py extract-coding --watch --interval 15 --settle 10 -o ctx.json
```

#### Files
- `cortex/continuous.py` — _FileState, CodingSessionWatcher, watch_coding_sessions(), debounce, extract-merge pipeline
- `tests/test_continuous.py` — 26 tests covering file detection, debounce, extraction pipeline, graph merge, callbacks, lifecycle, project filter
- `migrate.py` — `--watch`, `--interval`, `--settle`, `--context-refresh`, `--context-policy` flags on `extract-coding`

### Production Hardening (PR #13)

Six-agent codebase review identified and fixed cross-platform blockers before public release:

| Fix | What Changed | Why |
|-----|-------------|-----|
| Hook path quoting | `sys.executable` + `shlex.quote()` | Paths with spaces broke the hook command |
| Windows compatibility | `sys.executable` instead of hardcoded `python3` | `python3` doesn't exist on Windows |
| Robust hook matching | Match by `"cortex-hook.py" in command` | Old→new hook format migration, quoting differences |
| Atomic graph save | Write to `.tmp` then `os.replace()` | Crash during write can't corrupt the graph file |
| Error visibility | Extraction errors print to stderr | Silent `except Exception: pass` made debugging impossible |
| Deleted file cleanup | Remove stale entries from `_file_states` | Memory growth in long-running watcher daemons |
| Reversed marker safety | Validate `CORTEX:START` before `CORTEX:END` | Malformed markers could corrupt user's config files |
| JSON error handling | `run_verify()` catches `JSONDecodeError` + UTF-8 | Crash on malformed input files |

---

## Final Directory Structure (Actual)

```
chatbot-memory-skills/
├── cortex/
│   ├── __init__.py                  # v6.4.0
│   ├── graph.py                     # Phase 1: Node, Edge, CortexGraph (schema 6.0)
│   ├── compat.py                    # Phase 1: v4 ↔ v5 conversion
│   ├── temporal.py                  # Phase 2: Snapshot, drift
│   ├── contradictions.py            # Phase 2: ContradictionEngine
│   ├── timeline.py                  # Phase 2: Timeline views
│   ├── upai/                        # Phase 3: *** THE BREAKTHROUGH ***
│   │   ├── __init__.py
│   │   ├── identity.py              # UPAIIdentity, DID, Ed25519/HMAC signing
│   │   ├── disclosure.py            # DisclosurePolicy + apply_disclosure()
│   │   └── versioning.py            # VersionStore (commit/log/diff/checkout)
│   ├── adapters.py                  # Phase 3: Claude/SystemPrompt/Notion/GDocs adapters
│   ├── edge_extraction.py           # Phase 4: Pattern-based + proximity edge discovery
│   ├── cooccurrence.py              # Phase 4: Tiered co-occurrence (PMI/frequency)
│   ├── dedup.py                     # Phase 4: Graph-aware dedup (text + neighbor overlap)
│   ├── centrality.py                # Phase 4: Degree centrality + PageRank + confidence boost
│   ├── query.py                     # Phase 5: QueryEngine + BFS + union-find + betweenness
│   ├── intelligence.py              # Phase 5: GapAnalyzer + InsightGenerator
│   ├── coding.py                    # Phase 7: Coding session behavioral extraction
│   ├── hooks.py                     # Phase 7: Auto-inject context into Claude Code sessions
│   ├── context.py                   # Phase 7: Cross-platform context writer (6 platforms)
│   ├── continuous.py                # Phase 7: Real-time session watcher + incremental extraction
│   ├── viz/                         # Phase 6
│   │   ├── __init__.py
│   │   ├── layout.py                # Fruchterman-Reingold + caching + numpy fast path
│   │   └── renderer.py              # Interactive HTML (Canvas 2D) + static SVG
│   ├── dashboard/                   # Phase 6
│   │   ├── __init__.py
│   │   └── server.py                # stdlib HTTP server + AJAX dashboard
│   └── sync/                        # Phase 6
│       ├── __init__.py
│       ├── monitor.py               # os.stat() file polling auto-extraction
│       └── scheduler.py             # threading.Timer periodic platform sync
├── skills/
│   ├── chatbot-memory-extractor/
│   └── chatbot-memory-importer/
├── cortex-hook.py                   # Standalone hook entry point for Claude Code
├── tests/                           # 618 tests across 21 files
│   ├── test_features.py             # Original feature tests
│   ├── test_graph.py                # Phase 1
│   ├── test_temporal.py             # Phase 2
│   ├── test_contradictions.py       # Phase 2
│   ├── test_timeline.py             # Phase 2
│   ├── test_upai.py                 # Phase 3: UPAI identity + disclosure
│   ├── test_versioning.py           # Phase 3: Version store
│   ├── test_adapters.py             # Phase 3: Platform adapters
│   ├── test_edge_extraction.py      # Phase 4
│   ├── test_cooccurrence.py         # Phase 4
│   ├── test_dedup.py                # Phase 4
│   ├── test_query.py                # Phase 5
│   ├── test_intelligence.py         # Phase 5
│   ├── test_viz.py                  # Phase 6
│   ├── test_dashboard.py            # Phase 6
│   ├── test_monitor.py              # Phase 6
│   ├── test_scheduler.py            # Phase 6
│   ├── test_coding.py              # Phase 7
│   ├── test_hooks.py              # Phase 7: Auto-inject hook
│   ├── test_context.py            # Phase 7: Cross-platform context writer
│   └── test_continuous.py         # Phase 7: Continuous extraction
├── extract_memory.py                # Modified Phases 1, 2, 4, 7
├── import_memory.py                 # Modified Phases 1, 3
├── migrate.py                       # 23 subcommands (modified every phase)
├── docs/
│   └── cortex-roadmap-v2.md         # This document
├── marketplace.json
├── README.md
└── LICENSE
```

---

## Summary Table

| Phase | Version | Name | Status | Key Deliverables |
|-------|---------|------|--------|-----------------|
| 1 | v5.0 | Graph Foundation | **DONE** | Category-agnostic nodes with tags, v4↔v5 roundtrip |
| 2 | v5.1 | Temporal + Contradictions | **DONE** | Snapshots, drift scoring, contradiction detection |
| 3 | v5.2 | **UPAI Protocol** | **DONE** | Ed25519/HMAC signing, selective disclosure, version control, platform adapters |
| 4 | v5.3 | Smart Edges | **DONE** | Pattern-based + proximity extraction, co-occurrence, centrality, graph-aware dedup |
| 5 | v5.4 | Query + Intelligence | **DONE** | BFS/union-find/betweenness, gap analysis, weekly digest |
| 6 | v6.0 | Viz + Flywheel | **DONE** | FR layout, HTML/SVG viz, dashboard, file monitor, sync scheduler |
| 7 | v6.4 | Coding Tool Extraction | **DONE** | Behavioral extraction, auto-discovery, project enrichment, auto-inject hook, cross-platform context writer (6 platforms), continuous extraction with debounce, production hardened (PR #13) |

---

## Issues Resolved (from Staff Engineer Review)

| # | Issue | Resolution |
|---|-------|------------|
| 1 | Node identity model | Category-agnostic nodes with `tags: list[str]` |
| 2 | v4→v5 edge conversion | Explicit rules: resolve strings → edges, stubs for unresolved |
| 3 | v5 JSON schema | Full schema defined with `graph` + `categories` blocks |
| 4 | PMI on small datasets | Tiered: PMI ≥500, frequency 100-499, strict <100. Min count=3 |
| 5 | PageRank on tiny graphs | Degree centrality default. PageRank opt-in ≥200 nodes |
| 6 | Snapshot trigger | Per extraction/merge. Lightweight (confidence + hashes) |
| 7 | NL query expectations | Renamed "Structured Query Interface". NL = syntactic sugar |
| 8 | Push/pull reality | File-based I/O. Live API sync = future |
| 9 | Crypto threat model | Separated: integrity (SHA-256), ownership (Ed25519), authenticity |
| 10 | Phase ordering | Reordered: 1→2→3(UPAI)→4→5→6 |
| 11 | Optional deps | Three tiers: core, cortex[crypto], cortex[fast] |
| 12 | Extraction quality ceiling | Optional `--llm` flag in Phase 4 |

---

## Verification Strategy (Applied Per Phase)

**Per-phase gate (all phases passed):**
1. `python -m pytest tests/` — ALL tests pass (618 as of v6.4)
2. `python migrate.py <test_export> --to claude` — v4 output identical to pre-phase
3. v4→v5→v4 roundtrip produces empty diff
4. New CLI subcommands work with both v4 and v5 input
5. No new warnings, no regressions

---

## Competitive Landscape (as of Feb 2026)

Nobody is building this combination:

| Capability | Cortex | Mem0 | Letta | ChatGPT Memory | Claude Memory | OneContext |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Knowledge Graph | Yes | Partial | No | No | No | No |
| **Portability (UPAI)** | **Yes** | No | No | No | No | No |
| **User-Owned** | **Yes** | No | No | No | No | No |
| **Temporal Tracking** | **Yes** | No | No | No | No | No |
| **Coding Tool Extraction** | **Yes** | No | No | No | No | Partial |
| **Auto-Inject Context** | **Yes** | No | No | No | No | Yes |
| **Cross-Platform Context** | **Yes (6)** | No | No | No | No | No |
| Cross-Session Context | Yes | Yes | Yes | Yes | Yes | **Yes** |
| Team/Multi-User Sync | No | No | No | No | No | **Yes** |
| Zero-Dep / Local-First | Yes | No | No | N/A | N/A | No |

The breakthrough = **user-owned portable AI identity with selective disclosure**. That's Phase 3. Everything before it is infrastructure. Phase 7 extends extraction beyond chatbots into coding tools.

### OneContext (Feb 2026)

Closest new entrant. Built by Junde Wu (Oxford PhD). "Agent Self-Managed Context Layer" — records coding agent trajectories and syncs context across sessions, devices, and team members via Slack. GitHub: [TheAgentContextLab/OneContext](https://github.com/TheAgentContextLab/OneContext).

**Key differences from Cortex:**
- **Scope:** Coding agents only (Claude Code, Codex) vs all AI platforms + coding tools
- **Data model:** Opaque agent trajectories vs structured knowledge graph (nodes, edges, confidence, tags)
- **Ownership:** No cryptographic signing vs UPAI protocol (Ed25519, selective disclosure, version control)
- **Architecture:** Cloud-based sync vs offline/local-first, zero-dep
- **Intelligence:** Context replay vs query engine, gap analysis, temporal drift, contradiction detection

**Complementary, not competitive.** OneContext solves agent-side context sync. Cortex solves user-side identity ownership. Potential integration: Cortex could consume OneContext trajectories as an input source, or OneContext could load Cortex-exported context into new agent sessions.

---

## Completion Status

**All 7 phases shipped and production hardened.** Cortex v6.4.0 is the complete implementation of this roadmap.

| Metric | Value |
|--------|-------|
| Version | 6.4.0 |
| Schema | 6.0 |
| Total tests | 618 |
| Test files | 21 |
| CLI subcommands | 23 |
| External dependencies | 0 (core) |
| Backward compatible | v4 JSON roundtrip preserved |
| Cross-platform targets | 6 (Claude Code, Cursor, Copilot, Windsurf, Gemini CLI) |
| Production hardened | PR #13 — cross-platform review (8 fixes) |

**What's next:** See project discussions for future roadmap ideas (Cursor/Copilot parsers, live API sync, delta-based version store, LLM-assisted edge extraction, multi-user graph federation).
