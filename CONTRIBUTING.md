# Contributing to Cortex

Thank you for your interest in contributing to Cortex! This guide will help you get started.

## Prerequisites

- Python 3.10+
- Git

Examples below use `python3.11` so contributors do not accidentally pick up an older system `python3`/`pip` on macOS. Any supported Python 3.10+ interpreter is fine.

## Setup

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Running Tests

```bash
python -m pytest tests/
```

The full CLI/library suite should pass before you open a PR.

## Architecture Overview

```
cortex/
├── extract_memory.py   # Context extraction from AI platform exports
├── graph.py            # CortexGraph — knowledge graph data structure
├── import_memory.py    # Export to platform formats (Claude, Notion, etc.)
├── cli.py              # CLI entry point
├── search.py           # TF-IDF semantic search
├── query_lang.py       # Graph query language (DSL)
├── federation.py       # Cross-instance sharing
├── upai/               # UPAI protocol layer
│   ├── identity.py     # W3C did:key identity
│   ├── disclosure.py   # Disclosure policies (full, professional, etc.)
│   ├── keychain.py     # Key rotation
│   └── errors.py       # Structured error codes
├── sync/               # File-backed scheduling and monitor helpers
└── viz/                # Graph rendering helpers

tests/                  # CLI/core-library test suite
```

## Key Principles

- **Zero external dependencies** for the core package. All crypto helpers use stdlib only.
- **Optional extras**: `pynacl` for Ed25519, `numpy` for fast mode.
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
   python -m pytest tests/
   ```

4. **Keep commits focused** — one logical change per commit.

5. **Open a PR** against `main` with a clear description of what changed and why.

## Code Style

- Line length: 120 characters
- Linting: ruff with E, F, W, I rules
- Quote style: double quotes
- Target: Python 3.10+

## Dependency Management

- Runtime dependencies are pinned in `requirements.txt`.
- Development-only dependencies are pinned in `requirements-dev.txt`.
- `pyproject.toml` remains the packaging source of truth, while the requirements files provide reproducible install sets for local development and CI.
- Update policy:
  - change one dependency family at a time
  - rerun the full test suite after every dependency update
  - document any new dependency in `DEPENDENCIES.md`
  - prefer built-in modules unless a third-party package is clearly necessary

## What We're Looking For

- Bug fixes with test coverage
- New platform adapters following the pattern in `cortex/adapters/`
- Documentation improvements

## What to Avoid

- Adding runtime dependencies to the core package
- Breaking changes to the CLI or graph file formats without discussion
- Large refactors without prior discussion (open an issue first)

## Reporting Issues

Use the [issue templates](https://github.com/Junebugg1214/Cortex-AI/issues/new/choose) for bug reports and feature requests.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
