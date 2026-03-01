# CLAUDE.md — Cortex-AI

## Project Overview

Cortex-AI is a **knowledge graph engine** for portable AI identity. It extracts identity, preferences, and behavioral signals from chatbot/coding platform exports (OpenAI, Gemini, Perplexity, Claude, Cursor, etc.), structures them into a semantic graph, and exports to multiple platforms. The server component (CaaS — Context-as-a-Service) exposes the graph over HTTP with authentication, disclosure policies, and multi-instance federation via the UPAI identity framework.

- **Package name:** `cortex-identity`
- **Version:** 1.4.0
- **License:** MIT
- **Python:** >=3.10 (tested on 3.10, 3.11, 3.12, 3.13)
- **Zero required external dependencies** — core uses stdlib only. Optional: `pynacl` (crypto), `numpy` (fast), `psycopg` (postgres).

## Quick Reference

```bash
# Install (editable, with all optional deps)
pip install -e ".[full]"

# Install (dev only — pytest + pynacl)
pip install -e ".[dev]"

# Run all tests
python -m pytest tests/ -q --tb=short

# Lint
ruff check cortex/ tests/

# Format check
ruff format --check cortex/ tests/

# Format fix
ruff format cortex/ tests/

# Run CLI
cortex --help
cortex migrate <export-file> --to <platform>
cortex extract <export-file>
cortex export <context.json> --to <platform>
cortex serve <context.json> --port 8421
```

## Repository Structure

```
Cortex-AI/
├── cortex/                  # Main Python package
│   ├── __init__.py
│   ├── __main__.py          # python -m cortex entry point
│   ├── cli.py               # CLI (argparse): migrate, extract, import, export, hook, watch, query
│   ├── graph.py             # CortexGraph, Node, Edge — core data model (schema v5/v6)
│   ├── extract_memory.py    # AggressiveExtractor — multi-format data extraction
│   ├── import_memory.py     # NormalizedContext — multi-platform export functions
│   ├── adapters.py          # Platform adapters (Claude, Notion, GDocs, SystemPrompt)
│   ├── compat.py            # v4↔v5 graph format conversion
│   ├── hooks.py             # SessionStart hook for Claude Code
│   ├── _hook.py             # Hook entry point (cortex-hook CLI)
│   ├── context.py           # Cross-platform context writing (Claude, Cursor, Copilot, Windsurf, Gemini)
│   ├── contradictions.py    # ContradictionEngine — conflict detection (negation, temporal, source, tag)
│   ├── intelligence.py      # GapAnalyzer, InsightGenerator — graph health analysis
│   ├── query.py             # QueryEngine — graph traversal (BFS, shortest path, components)
│   ├── query_lang.py        # DSL tokenizer/parser (FIND, NEIGHBORS, PATH, SEARCH)
│   ├── search.py            # TFIDFIndex — in-memory semantic search
│   ├── dedup.py             # Deduplication (text similarity + neighbor overlap)
│   ├── temporal.py          # Temporal snapshots and drift scoring
│   ├── timeline.py          # TimelineGenerator — chronological event views
│   ├── continuous.py        # CodingSessionWatcher — live Claude Code extraction
│   ├── coding.py            # Coding session metadata extraction
│   ├── federation.py        # FederationManager — signed cross-instance graph sharing
│   ├── centrality.py        # Graph centrality algorithms
│   ├── cooccurrence.py      # Co-occurrence analysis
│   ├── edge_extraction.py   # Edge extraction from text
│   ├── professional_timeline.py  # Work/education history parsing
│   ├── completion.py        # Shell autocompletion
│   ├── caas/                # Context-as-a-Service HTTP server
│   │   ├── server.py        # HTTP API (stdlib http.server) — 50+ endpoints
│   │   ├── config.py        # INI + env-var configuration (CortexConfig)
│   │   ├── storage.py       # Abstract grant/webhook/policy stores
│   │   ├── sqlite_store.py  # SQLite storage backend
│   │   ├── postgres_store.py # PostgreSQL storage backend
│   │   ├── audit_ledger.py  # Hash-chained audit logs
│   │   ├── sqlite_audit_ledger.py
│   │   ├── postgres_audit_ledger.py
│   │   ├── security.py      # CSRF, SSRF protection
│   │   ├── rate_limit.py    # Rate limiting
│   │   ├── encryption.py    # Payload encryption
│   │   ├── oauth.py         # OAuth provider integration
│   │   ├── circuit_breaker.py
│   │   ├── event_buffer.py  # SSE buffering
│   │   ├── webhook_worker.py
│   │   ├── caching.py       # ETag support
│   │   ├── correlation.py   # Request ID tracking
│   │   ├── tracing.py       # Distributed tracing
│   │   ├── instrumentation.py # Metrics collection
│   │   ├── metrics.py
│   │   ├── profile.py       # Public profile endpoint
│   │   ├── api_keys.py
│   │   ├── validation.py    # Input validation
│   │   ├── migrations.py    # Schema versioning
│   │   ├── dashboard/       # Embedded SPA dashboard
│   │   └── webapp/          # Web application static assets
│   ├── upai/                # UPAI identity framework
│   │   ├── identity.py      # UPAIIdentity — Ed25519/HMAC cryptographic identity
│   │   ├── tokens.py        # GrantToken — three-part signed tokens
│   │   ├── disclosure.py    # DisclosurePolicy — node visibility control
│   │   ├── schemas.py       # JSON Schema validators
│   │   ├── errors.py        # Structured error codes (UPAI-4xxx/5xxx)
│   │   ├── error_hints.py   # User-friendly error messages
│   │   ├── rbac.py          # Role-based access control
│   │   ├── credentials.py   # OAuth/API key management
│   │   ├── keychain.py      # Secure credential storage
│   │   ├── attestations.py  # Proof of ownership
│   │   ├── backup.py        # Graph backup
│   │   ├── versioning.py    # Version store + history
│   │   ├── pagination.py    # Cursor-based pagination
│   │   ├── discovery.py     # UPAI discovery endpoint
│   │   └── webhooks.py      # Webhook registration
│   ├── sdk/                 # Embedded Python SDK client
│   │   ├── client.py        # CortexClient — sync HTTP client (stdlib urllib)
│   │   └── exceptions.py
│   ├── dashboard/           # Local dashboard server
│   │   └── server.py        # Canvas graph visualization SPA
│   ├── sync/                # Sync utilities
│   │   ├── monitor.py       # File monitoring
│   │   └── scheduler.py     # Task scheduling
│   ├── viz/                 # Visualization
│   │   ├── layout.py        # Graph layout algorithms
│   │   └── renderer.py      # Rendering output
│   └── plugins/             # Plugin system
│       ├── example_logger.py
│       └── example_validator.py
├── sdk/                     # Standalone SDK packages
│   ├── python/              # Python SDK (separate package)
│   │   ├── cortex_sdk/
│   │   └── pyproject.toml
│   └── typescript/          # TypeScript SDK (npm package)
│       ├── src/
│       ├── package.json
│       └── tsconfig.json
├── skills/                  # Claude Code skills
│   ├── chatbot-memory-extractor/
│   └── chatbot-memory-importer/
├── tests/                   # 95 test modules (~31K lines)
├── examples/                # Example applications
│   ├── chatbot-memory/
│   ├── multi-agent/
│   └── sdk-quickstart/
├── docs/                    # Documentation
│   ├── architecture.md
│   ├── user-guide.md
│   ├── development.md
│   ├── deployment.md
│   ├── cli-walkthrough.md
│   ├── security.md
│   ├── threat-model.md
│   ├── error-guide.md
│   └── ...
├── deploy/                  # Deployment configs
│   ├── cortex.ini           # Server configuration
│   ├── cortex.service       # systemd unit
│   ├── nginx.conf           # Reverse proxy
│   ├── Caddyfile
│   ├── prometheus.yml
│   ├── .env.example
│   ├── helm/cortex/         # Kubernetes Helm chart
│   └── grafana/             # Grafana dashboards
├── benchmarks/              # Performance benchmarks
├── spec/                    # Specifications
│   ├── openapi.json         # OpenAPI spec
│   └── upai-v1.0.md         # UPAI protocol spec
├── assets/                  # Static assets (images, etc.)
├── pyproject.toml           # Build config, deps, tool settings
├── Dockerfile               # Multi-stage production image
├── docker-compose.yml       # Full stack (cortex + postgres + prometheus + grafana)
├── migrate.py               # Root-level CLI stub
└── cortex-hook.py           # Root-level hook stub
```

## Development Workflow

### Setting Up

```bash
# Clone and install
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
pip install -e ".[dev]"        # pytest + pynacl
# or
pip install -e ".[full]"       # all optional deps (pynacl, numpy, psycopg)
```

### Running Tests

```bash
# All tests
python -m pytest tests/ -q --tb=short

# Single test file
python -m pytest tests/test_graph.py -q

# Single test
python -m pytest tests/test_graph.py::TestCortexGraph::test_add_node -q

# With verbose output
python -m pytest tests/ -v
```

Tests use both `unittest.TestCase` and pytest fixture styles. The test directory is flat (all files in `tests/`). Tests are configured in `pyproject.toml`:
- `testpaths = ["tests"]`
- `pythonpath = ["."]`

### Linting and Formatting

The project uses **ruff** for both linting and formatting.

```bash
# Lint (errors, pyflakes, warnings, import sorting)
ruff check cortex/ tests/

# Auto-fix lint issues
ruff check --fix cortex/ tests/

# Check formatting
ruff format --check cortex/ tests/

# Apply formatting
ruff format cortex/ tests/
```

**Ruff configuration** (from `pyproject.toml`):
- Target: Python 3.10
- Line length: 120
- Lint rules: E (PEP 8), F (pyflakes), W (warnings), I (isort)
- Ignored: E501 (line too long)
- Quote style: double quotes

### CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`):
1. **Lint** — ruff check + format check (Python 3.12)
2. **Test** — pytest across Python 3.10, 3.11, 3.12, 3.13
3. **Docker** — build image, health check (after lint + test pass)

CI triggers on pushes to `main` and `phase*` branches, and on PRs to `main`.

### Docker

```bash
# Build
docker build -t cortex-ai .

# Run
docker run -p 8421:8421 cortex-ai

# Full stack with monitoring
docker compose --profile postgres --profile monitoring up
```

The Dockerfile uses multi-stage build with a non-root `cortex` user. The server listens on port **8421**.

## Architecture & Key Concepts

### Core Data Model

The knowledge graph (`cortex/graph.py`) consists of:
- **Nodes**: Entities with `id` (SHA-256 hash), `label`, `tags` (category membership), `confidence` (0.0-1.0), `snapshots` (temporal history)
- **Edges**: Relationships between nodes with `relation` type and temporal metadata
- **Categories**: `identity`, `professional_context`, `technical_expertise`, `values`, `relationships`, `negations`, etc. (19 total in CATEGORY_ORDER)

### Data Pipeline

1. **Extract** — `AggressiveExtractor` parses platform exports (ZIP, JSON, JSONL, text)
2. **Structure** — Creates v4 context dict, upgrades to v5 graph with multi-tag nodes
3. **Analyze** — Contradiction detection, gap analysis, deduplication
4. **Export** — Platform-specific formats (Claude, Notion, GDocs, system prompts)
5. **Serve** — CaaS HTTP API with disclosure policies and grant tokens

### Schema Versions

- **v4**: Category-based dict (`{category: [topics]}`) — flat, used for import/export
- **v5/v6**: Full graph with nodes, edges, metadata — used internally
- `cortex/compat.py` handles bidirectional conversion (upgrade is lossless, downgrade is lossy)

### UPAI Identity

- Ed25519 cryptographic identity (with HMAC-SHA256 stdlib fallback)
- DID-based addressing (`did:key:z6Mk...`)
- Grant tokens for API access with scoped permissions
- Disclosure policies control what data is visible to which consumers

### Disclosure Policies

Built-in policies: `full`, `professional`, `technical`, `minimal`. Custom policies filter by tags, confidence thresholds, property redaction, and max nodes.

### Confidence Scoring

- Base: 0.85 (explicit statement) down to 0.3 (inferred)
- Boosted by mention frequency (+0.0 to +0.3)
- Decayed by time (1.0 within a week, 0.1 after a year)

## Conventions

### Code Style

- **Double quotes** for strings
- **120 character** line length
- **Type hints** on public APIs
- **Dataclasses** for structured data (Node, Edge, Snapshot, etc.)
- **No external deps** in core — stdlib only; optional deps guarded by try/except imports
- **Thread safety** — locks on shared state (stores, registries, graph instances)

### Module Patterns

- **Adapter pattern**: `cortex/adapters.py` — `BaseAdapter` with push/pull interface
- **Strategy pattern**: Multiple extractors routed by format type
- **Registry pattern**: `BUILTIN_POLICIES`, `CATEGORY_ORDER`, adapter dispatch tables
- **Temporal snapshots**: Point-in-time node states for history tracking

### File Naming

- Test files mirror source: `cortex/graph.py` → `tests/test_graph.py`
- CaaS-specific tests prefixed: `test_caas_*.py`
- Phase-specific tests: `test_phase7_cli.py`, `test_phase8_metrics.py`

### Error Handling

- UPAI errors use structured codes: `UPAI-4xxx` (client), `UPAI-5xxx` (server)
- `cortex/upai/error_hints.py` provides user-friendly remediation advice
- Input validation at system boundaries (API endpoints, CLI args, file parsing)

### Testing Conventions

- Prefer `unittest.TestCase` for class-based tests, pytest fixtures for simpler ones
- Use `tempfile` for file-based tests — clean up after
- Mock external resources; no network calls in tests
- Tests run quickly — no long-running integration tests in the default suite

## Key Files to Understand First

When onboarding, read these files in order:

1. `cortex/graph.py` — Core data model (Node, Edge, CortexGraph)
2. `cortex/extract_memory.py` — How data enters the system
3. `cortex/import_memory.py` — How data leaves the system (export functions)
4. `cortex/cli.py` — CLI interface and command routing
5. `cortex/compat.py` — Schema version conversion
6. `cortex/upai/disclosure.py` — Policy-based data filtering
7. `cortex/caas/server.py` — HTTP API endpoints

## Common Tasks

### Adding a New Export Format

1. Add export function in `cortex/import_memory.py` (takes `NormalizedContext`, returns formatted string)
2. Add adapter in `cortex/adapters.py` (extend `BaseAdapter`)
3. Register in CLI dispatch table in `cortex/cli.py`
4. Add tests in `tests/`

### Adding a New Extraction Source

1. Add parser logic in `cortex/extract_memory.py` (`AggressiveExtractor`)
2. Add format detection/routing in `cortex/cli.py` (`_run_extraction`)
3. Add tests with sample data

### Adding a CaaS Endpoint

1. Add handler method to `CaaSHandler` in `cortex/caas/server.py`
2. Add route to the dispatch table
3. Add input validation in `cortex/caas/validation.py` if needed
4. Update `spec/openapi.json`
5. Add tests in `tests/test_caas_server.py`

### Adding a New Disclosure Policy

1. Add to `BUILTIN_POLICIES` in `cortex/upai/disclosure.py`
2. Define `include_tags`, `exclude_tags`, `min_confidence`, etc.
3. Add tests

## Environment Variables

Server configuration supports env-var overrides with the pattern `CORTEX_<SECTION>_<KEY>`:

- `CORTEX_SERVER_HOST` / `CORTEX_SERVER_PORT`
- `CORTEX_STORAGE_BACKEND` (`sqlite` or `postgres`)
- `CORTEX_STORAGE_DB_PATH`
- `CORTEX_LOGGING_LEVEL` / `CORTEX_LOGGING_FORMAT`
- `CORTEX_SECURITY_CSRF_ENABLED` / `CORTEX_SECURITY_SSRF_PROTECTION`
- `CORTEX_SSE_ENABLED` / `CORTEX_SSE_BUFFER_SIZE`

See `deploy/.env.example` for the full list.

## Important Notes

- The CaaS server runs on port **8421** by default
- Graph IDs are deterministic SHA-256 hashes of normalized labels
- The `cortex-hook.py` and `migrate.py` root scripts are backward-compat stubs for users running from a cloned repo without pip install
- The project publishes to PyPI (`cortex-identity`) and npm (`sdk/typescript/`)
- Docker images push to `ghcr.io/junebugg1214/cortex-ai`
