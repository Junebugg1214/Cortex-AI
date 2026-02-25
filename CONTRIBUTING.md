# Contributing to Cortex

Thank you for your interest in contributing to Cortex! This guide will help you get started.

## Prerequisites

- Python 3.10+
- Git

## Setup

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
pip install -e ".[dev]"
```

## Running Tests

```bash
python3 -m pytest tests/
```

All 2,361+ tests should pass. 35 PostgreSQL-specific tests are skipped unless `psycopg` is installed and a database is available.

## Architecture Overview

```
cortex/
├── extract_memory.py   # Context extraction from AI platform exports
├── graph.py            # CortexGraph — knowledge graph data structure
├── import_memory.py    # Export to platform formats (Claude, Notion, etc.)
├── cli.py              # CLI entry point (30+ subcommands)
├── search.py           # TF-IDF semantic search
├── query_lang.py       # Graph query language (DSL)
├── federation.py       # Cross-instance sharing
├── plugins/            # Hook-based plugin system
├── upai/               # UPAI protocol layer
│   ├── identity.py     # W3C did:key identity
│   ├── tokens.py       # Grant token signing/verification
│   ├── disclosure.py   # Disclosure policies (full, professional, etc.)
│   ├── rbac.py         # Role-based access control (4 roles, 10 scopes)
│   ├── keychain.py     # Key rotation
│   └── errors.py       # Structured error codes
├── caas/               # Context-as-a-Service HTTP API
│   ├── server.py       # HTTP request handlers
│   ├── storage.py      # Abstract storage interfaces
│   ├── sqlite_store.py # SQLite backend
│   ├── postgres_store.py # PostgreSQL backend
│   ├── config.py       # INI + env var configuration
│   ├── instrumentation.py # Prometheus metrics
│   ├── archive.py      # ZIP archive export/import
│   ├── qr.py           # QR code generation
│   └── profile.py      # Public profile management
sdk/
├── python/             # Python SDK (stdlib-only)
└── typescript/         # TypeScript SDK (@cortex_ai/sdk)

examples/               # Sample scripts and integration patterns
```

### TypeScript SDK

```bash
cd sdk/typescript
npm install
npm test          # Runs node:test suite
npm run build     # ESM + CJS dual build
```

## Key Principles

- **Zero external dependencies** for the core package. All crypto helpers use stdlib only.
- **Optional extras**: `pynacl` for Ed25519, `numpy` for fast mode, `psycopg` for PostgreSQL.
- **Every PR must pass all tests** — no regressions allowed.
- **Type hints** on all public APIs.
- **Backward compatible** — don't break existing behavior.

## Making Changes

1. **Fork and branch** from `main`:
   ```bash
   git checkout -b feature/my-change
   ```

2. **Write tests** for any new functionality. Place tests in `tests/`.

3. **Run the full test suite** before submitting:
   ```bash
   python3 -m pytest tests/
   ```

4. **Keep commits focused** — one logical change per commit.

5. **Open a PR** against `main` with a clear description of what changed and why.

## Code Style

- Line length: 120 characters
- Linting: ruff with E, F, W, I rules
- Quote style: double quotes
- Target: Python 3.10+

## What We're Looking For

- Bug fixes with test coverage
- Performance improvements with benchmarks
- New storage backends following the `Abstract*` interfaces in `cortex/caas/storage.py`
- New platform adapters following the pattern in `cortex/adapters/`
- Documentation improvements

## What to Avoid

- Adding runtime dependencies to the core package
- Breaking changes to the CaaS API or UPAI protocol
- Large refactors without prior discussion (open an issue first)

## Reporting Issues

Use the [issue templates](https://github.com/Junebugg1214/Cortex-AI/issues/new/choose) for bug reports and feature requests.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
