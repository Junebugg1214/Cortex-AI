# Git For AI Memory

Cortex now has the core local primitives for a `Git for AI Memory` workflow:

- `commit`: snapshot the current graph
- `log`: inspect the memory history
- `diff`: compare versions
- `checkout`: restore an older snapshot
- `blame`: trace a claim to provenance and version history
- `memory retract`: remove memory evidence from a bad source
- `query --at`: inspect what was true at a point in time

## Why This Matters

Most AI memory systems are opaque. They store context, but they do not answer:

- Where did this claim come from?
- When was it true?
- What changed between runs?
- How do I roll back a bad import?
- How do I remove everything that came from one source?

Cortex answers those questions locally, with files you control.

## MVP Demo

```bash
# Extract memory into a local graph
cortex extract notes.json -o context.json

# Save a versioned snapshot
cortex commit context.json -m "Import product planning notes"

# Manually refine a claim with provenance
cortex memory set context.json \
  --label "Project Atlas" \
  --tag active_priorities \
  --status active \
  --valid-from 2026-03-01T00:00:00Z \
  --source planning-notes

# Commit the change
cortex commit context.json -m "Promote Project Atlas to active"

# Explain why the claim exists
cortex blame context.json --label "Project Atlas"

# Compare versions
cortex diff <old-version> <new-version>

# Query what was true at a given time
cortex query context.json --node "Project Atlas" --at 2026-03-15T00:00:00Z

# Retract a bad source
cortex memory retract context.json --source planning-notes
```

## What Cortex Can Explain Today

- current tags, aliases, confidence, lifecycle, and validity window
- provenance sources on the current node
- snapshot sources that observed the claim
- version where the claim first appeared
- most recent version that still contained the claim
- which stored versions materially changed the claim

## Next Logical Steps

- branch and merge workflows for memory histories
- per-claim provenance ledgers instead of node-level aggregation
- `blame --source` and `blame --version` filters
- first-class claim IDs for rename-safe history tracking
- UI for receipts, diffs, and retractions
