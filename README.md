# Cortex

Own your AI ID.

Cortex is a CLI-only toolkit for portable AI memory and identity.
You control your data and work with local files you can inspect and version.

## Open Source Scope

- Local CLI workflows only
- No HTTP server, web app, hosted backend, or SDK surface
- Designed for developer-owned files, portability, and versioned graph history

## Install

```bash
pip install cortex-identity
```

Extras:

```bash
pip install cortex-identity[crypto]
pip install cortex-identity[fast]
pip install cortex-identity[full]
```

## CLI Quickstart

```bash
# Build graph from export
cortex extract <export-file> -o context.json

# Inspect
cortex stats context.json

# Export to target formats
cortex import context.json --to all -o ./output
```

## Common Commands

```bash
cortex extract <file> -o context.json
cortex import context.json --to claude -o ./output
cortex query context.json --node "Python"
cortex timeline context.json --format md
cortex contradictions context.json
cortex identity --init --name "Your Name"
```

## Repository Layout

- `cortex/`: core CLI, graph, extraction, import/export, identity, and versioning code
- `tests/`: CLI/core-library test suite

## License

MIT
