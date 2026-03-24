# Cortex

Own your AI memory and identity.

Cortex is a local toolkit for portable AI memory, identity, versioned graph history, and a lightweight infrastructure UI.
It turns exports, notes, and context captures into files you can inspect, compare, query, sign, and share.
Think of it as the beginning of **Git for AI Memory**: commits, branches, merges, review gates, receipts, retraction, claim workflows, and time-aware agent memory.

## What it does

- Builds a graph from exports or captured notes
- Lets you inspect stats, timelines, contradictions, and memory conflicts
- Stores memory and context locally in files you can version
- Initializes and signs UPAI identity material
- Exports compact context for downstream tools
- Writes context into coding-tool config files
- Integrates with local tools such as OpenClaw through the CLI
- Exposes a small local web UI for review, blame, history, governance, and remote sync

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

- Local CLI and local web UI workflows
- No hosted backend or managed cloud surface
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
cortex merge main
cortex review context.json --against main
cortex review context.json --against main --fail-on contradictions,temporal_gaps --format md
cortex merge feature/project-atlas --conflicts
cortex merge --resolve <conflict-id> --choose incoming
cortex merge --commit-resolved
cortex log
cortex diff <version-a> <version-b>
cortex checkout <version> -o restored.json
cortex blame context.json --label "PostgreSQL"
cortex blame context.json --label "PostgreSQL" --source manual-note --ref feature/project-atlas
cortex history context.json --label "PostgreSQL" --ref main
cortex claim log --label "PostgreSQL"
cortex claim log --label "PostgreSQL" --version abc123
cortex claim accept context.json <claim-id>
cortex claim reject context.json <claim-id>
cortex claim supersede context.json <claim-id> --label "PostgreSQL 16" --status active
cortex rollback context.json --to <version>
cortex governance allow protect-main --actor "agent/*" --action write --namespace main --approval-below-confidence 0.75
cortex remote add origin /path/to/other/store
cortex remote push origin --branch main
cortex ui --context-file context.json
cortex ingest github issue.json -o context.json
cortex ingest slack ./slack-export -o context.json
cortex ingest docs ./docs -o context.json
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
cortex review context.json --against main

# 4b. Make review CI-strict or CI-relaxed
cortex review context.json --against main --fail-on contradictions,temporal_gaps --format md
cortex review context.json --against main --fail-on none --format json

# 5. Ask why a claim exists
cortex blame context.json --label "Project Atlas"

# 5b. Inspect receipts from one source on one branch
cortex blame context.json --label "Project Atlas" --source planning-doc-v1 --ref experiment/planning-cleanup

# 5c. Inspect claim events directly
cortex claim log --label "Project Atlas"
cortex claim show <claim-id>

# 5d. Accept, reject, or supersede a claim directly
cortex claim accept context.json <claim-id>
cortex claim reject context.json <claim-id>
cortex claim supersede context.json <claim-id> --status active --valid-from 2026-04-01T00:00:00Z

# 5e. Inspect the chronological receipts timeline
cortex history context.json --label "Project Atlas" --ref experiment/planning-cleanup

# 6. Retract a bad source if needed
cortex memory retract context.json --source planning-doc-v1

# 7. Resolve merge conflicts if needed
cortex merge experiment/planning-cleanup
cortex merge --conflicts
cortex merge --resolve <conflict-id> --choose incoming
cortex merge --commit-resolved

# 8. Ingest local GitHub/Slack/docs sources
cortex ingest github issue.json -o context.json
cortex ingest slack ./slack-export -o context.json
cortex ingest docs ./docs -o context.json

# 9. Query historical truth
cortex query context.json --node "Project Atlas" --at 2026-04-01T00:00:00Z

# 10. Launch the local infrastructure UI
cortex ui --context-file context.json
```

## Infrastructure UI

Cortex now ships with a small local web app for the operational side of Git for AI Memory:

- review and semantic drift inspection
- blame and history receipts
- governance policy management
- explicit remote push, pull, and fork flows

Run it with:

```bash
cortex ui --context-file context.json
```

## Memory CI

The repo now includes [`.github/workflows/memory-review.yml`](/Users/marcsaint-jour/Desktop/Cortex-AI/.github/workflows/memory-review.yml), which:

- compares the checked-in memory file against the base branch version
- emits a Markdown review summary in GitHub Actions
- uploads JSON and Markdown review artifacts
- fails only on the gates you choose, such as `contradictions` and `temporal_gaps`

You can customize the same behavior locally with:

```bash
cortex review context.json --against main --fail-on contradictions,temporal_gaps --format md
cortex review context.json --against main --fail-on none --format json
```

## OpenClaw Integration

OpenClaw can use Cortex as a local memory layer, so the assistant can preview context, explain why it answered a certain way, surface conflicts, and sync coding context without needing a server.

## Repository Layout

- `cortex/`: core CLI, graph, extraction, import/export, identity, and versioning code
- `tests/`: CLI/core-library test suite

## License

MIT
