# Cortex

Own your AI memory and identity.

Cortex is a CLI-only toolkit for local, portable AI memory, identity, and versioned graph history.
It turns exports, notes, and context captures into files you can inspect, compare, query, sign, and share.
Think of it as the beginning of **Git for AI Memory**: commits, branches, diffs, checkout, blame, retraction, and time-aware claims for agent context.

## What it does

- Builds a graph from exports or captured notes
- Lets you inspect stats, timelines, contradictions, and memory conflicts
- Stores memory and context locally in files you can version
- Initializes and signs UPAI identity material
- Exports compact context for downstream tools
- Writes context into coding-tool config files
- Integrates with local tools such as OpenClaw through the CLI

## Why it matters

Think of Cortex as a notebook for your AI: local, portable, and easy to audit.

Examples:

- Remember that you prefer concise answers
- Track what your assistant knew on a given day
- Compare two graph snapshots and see what changed
- Feed a coding assistant the same context every time
- Keep identity and memory portable across machines
- Explain exactly why a claim exists, where it came from, and when it was true

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
cortex commit context.json -m "Import meeting notes"
cortex branch feature/project-atlas
cortex switch feature/project-atlas
cortex log
cortex diff <version-a> <version-b>
cortex checkout <version> -o restored.json
cortex blame context.json --label "PostgreSQL"
cortex claim log --label "PostgreSQL"
cortex query context.json --node "Python"
cortex query context.json --node "Current Project" --at 2026-06-01T00:00:00Z
cortex timeline context.json --format md
cortex contradictions context.json
cortex identity --init --name "Your Name"
cortex memory show context.json --tag technical_expertise
cortex memory set context.json --label "Response Style" --tag communication_preferences --brief "Prefers concise answers"
cortex memory retract context.json --source meeting-notes-2026-03-22
cortex memory conflicts context.json
cortex context-export context.json
cortex context-hook install context.json
cortex context-write context.json
```

## Git For AI Memory Workflow

```bash
# 1. Extract or edit local AI memory
cortex extract chat-export.json -o context.json

# 2. Commit the memory snapshot
cortex commit context.json -m "Import March planning notes"

# 3. Create a parallel memory branch for an experiment
cortex branch experiment/planning-cleanup
cortex switch experiment/planning-cleanup

# 4. Inspect what changed
cortex log
cortex diff main experiment/planning-cleanup

# 5. Ask why a claim exists
cortex blame context.json --label "Project Atlas"

# 5b. Inspect claim events directly
cortex claim log --label "Project Atlas"

# 6. Retract a bad source if needed
cortex memory retract context.json --source planning-doc-v1

# 7. Query historical truth
cortex query context.json --node "Project Atlas" --at 2026-04-01T00:00:00Z
```

## OpenClaw Integration

OpenClaw can use Cortex as a local memory layer, so the assistant can preview context, explain why it answered a certain way, surface conflicts, and sync coding context without needing a server.

## Repository Layout

- `cortex/`: core CLI, graph, extraction, import/export, identity, and versioning code
- `tests/`: CLI/core-library test suite

## License

MIT
