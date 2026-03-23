# Git For AI Memory

Cortex now has the core local primitives for a `Git for AI Memory` workflow:

- `commit`: snapshot the current graph
- `branch` / `switch`: create parallel memory histories and move between them
- `merge`: combine branch histories with conflict detection
- `review`: compare a branch or working graph against a baseline and flag memory risk
- `log`: inspect the memory history
- `diff`: compare versions
- `checkout`: restore an older snapshot
- `blame`: trace a claim to provenance and version history
- `history`: inspect chronological receipts for a node across versions and claim events
- `claim log` / `claim show`: inspect raw claim events
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

# Create an experimental memory branch
cortex branch experiment/slack-import
cortex switch experiment/slack-import

# Review the current graph before merging
cortex review context.json --against main

# Explain why the claim exists
cortex blame context.json --label "Project Atlas"

# Focus blame on one source and one branch
cortex blame context.json --label "Project Atlas" --source planning-notes --ref experiment/slack-import

# Inspect the receipts timeline
cortex history context.json --label "Project Atlas" --ref experiment/slack-import

# Inspect claim events directly
cortex claim log --label "Project Atlas"
cortex claim log --label "Project Atlas" --version abc123
cortex claim show <claim-id>

# Compare versions
cortex diff <old-version> <new-version>

# Merge when review passes
cortex merge experiment/slack-import

# Query what was true at a given time
cortex query context.json --node "Project Atlas" --at 2026-03-15T00:00:00Z

# Retract a bad source
cortex memory retract context.json --source planning-notes
```

## What Cortex Can Explain Today

- current tags, aliases, confidence, lifecycle, and validity window
- provenance sources on the current node
- branch-aware version ancestry for the active memory line
- merge conflicts when branches disagree on the same claim
- snapshot sources that observed the claim
- version where the claim first appeared
- most recent version that still contained the claim
- which stored versions materially changed the claim
- source-filtered and branch-filtered receipts for one claim

## Next Logical Steps

- per-claim provenance ledgers instead of node-level aggregation
- `blame --source` and `blame --version` filters
- first-class claim IDs for rename-safe history tracking
- UI for receipts, diffs, and retractions
