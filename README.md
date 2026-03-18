# Cortex

Own your AI memory and identity.

Cortex is a CLI-only toolkit for local, portable AI memory, identity, and versioned graph history.
It turns exports, notes, and context captures into files you can inspect, query, compare, sign, and share.

## What it does

- Builds a graph from exports or captured notes
- Lets you inspect stats, timelines, contradictions, and memory conflicts
- Stores memory and context locally in files you can version
- Initializes and signs UPAI identity material
- Exports compact context for downstream tools
- Writes context into coding-tool config files
- Integrates with local tools such as OpenClaw through the CLI

## Why it is useful

Think of Cortex as a notebook for your AI that you can read, edit, and audit.

Examples:

- Remember that you prefer concise answers
- Track what your assistant knew on a given day
- Compare two graph snapshots and see what changed
- Feed a coding assistant the same context every time
- Keep identity and memory portable across machines

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
cortex memory show context.json --tag technical_expertise
cortex memory set context.json --label "Response Style" --tag communication_preferences --brief "Prefers concise answers"
cortex memory conflicts context.json
cortex context-export context.json
cortex context-hook install context.json
cortex context-write context.json
```

## OpenClaw Integration

OpenClaw can use Cortex as a local memory layer, so the assistant can preview context, explain why it answered a certain way, surface conflicts, and sync coding context without needing a server.

## Repository Layout

- `cortex/`: core CLI, graph, extraction, import/export, identity, and versioning code
- `tests/`: CLI/core-library test suite

## License

MIT
