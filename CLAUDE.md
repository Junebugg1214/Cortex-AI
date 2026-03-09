# CLAUDE.md — Cortex-AI

## Project Overview

Cortex-AI is a CLI-only toolkit for portable AI identity and local memory graphs.
It extracts structured context from chat exports and coding sessions, stores that
context as local graph files, and exports compact views for downstream tools.

- Package name: `cortex-identity`
- License: MIT
- Python: 3.10+
- Runtime model: local files only, no server, no web app, no hosted backend

## Core Capabilities

- Extract graph data from chat exports and plain text
- Analyze local graphs with querying, timelines, contradictions, drift, and visualization
- Export filtered context to downstream formats such as Claude, Notion, Google Docs, and system prompts
- Manage local UPAI identity material and graph version history
- Inject compact context into coding tools such as Claude Code, Cursor, Copilot, Windsurf, and Gemini CLI

## Repository Structure

```text
Cortex-AI/
├── cortex/              # Main Python package
│   ├── cli.py           # CLI entry point
│   ├── extract_memory.py
│   ├── import_memory.py
│   ├── graph.py
│   ├── query.py
│   ├── timeline.py
│   ├── contradictions.py
│   ├── coding.py
│   ├── hooks.py
│   ├── context.py
│   ├── sync/            # File monitoring and scheduling helpers
│   ├── upai/            # Identity, disclosure, schemas, versioning
│   └── viz/             # Graph rendering helpers
├── tests/               # CLI/core-library test suite
├── pyproject.toml
├── README.md
├── migrate.py
└── cortex-hook.py
```

## Common Commands

```bash
cortex extract <export-file> -o context.json
cortex import context.json --to all -o ./output
cortex query context.json --node "Python"
cortex timeline context.json --format md
cortex identity --init --name "Your Name"
cortex context-write context.json --platforms claude-code cursor
```

## Development

```bash
pip install -e ".[dev]"
python3 -m pytest tests/
ruff check cortex/ tests/
ruff format cortex/ tests/
```
