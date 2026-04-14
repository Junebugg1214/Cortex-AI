# Your AI memory. Versioned. Portable. Yours.

Cortex gives your tools one user-owned Mind, with commits, branches, mounts, and portable exports on disk instead of memory locked inside one product.

[![PyPI version](https://img.shields.io/pypi/v/cortex-identity)](https://pypi.org/project/cortex-identity/)

[![Python versions](https://img.shields.io/pypi/pyversions/cortex-identity)](https://pypi.org/project/cortex-identity/) [![License: MIT](https://img.shields.io/github/license/Junebugg1214/Cortex-AI)](LICENSE)

[![GitHub stars](https://img.shields.io/github/stars/Junebugg1214/Cortex-AI?style=social)](https://github.com/Junebugg1214/Cortex-AI/stargazers)

You've taught one model how you work.
You open another tool because the task changed.
Your stack, constraints, and preferences stay behind in a product-specific memory system.
So you restate the same context again, or you keep working with the wrong context attached.

## The capability that changes everything

```
$ cortex source ingest policy_v3.pdf --mind compliance-kb
  Source ID:  doc-001 (sha256: 4f3a...c91e)
  Extracted:  14 facts, 3 claims, 2 relationships
  Ingested.   Lineage attached to all nodes.
```

Six hours later, the source is wrong. Retract it.

```
$ cortex source retract doc-001 --mind compliance-kb --dry-run
  DRY RUN — no changes written

  Retraction scope:
    Facts to remove:        14
    Claims to retract:       3
    Relationships to prune:  2
    Derived artifacts:       2  (brief, process update)

  All nodes carry lineage: doc-001
  No orphaned facts detected.
```

```
$ cortex source retract doc-001 --mind compliance-kb --confirm
  Pruning facts...           [==============] 14/14
  Retracting claims...       [===========  ]  3/3
  Removing relationships...  [=============]  2/2
  Invalidating artifacts...  [=============]  2/2

  Retraction complete.
  Graph clean. Audit trail written.
```

A vector database deletes the file. The 14 facts and 2 derived artifacts keep answering queries. Cortex traces every node back to its source and prunes the entire downstream graph.

## See it in 30 seconds

```
$ cortex init
# Initialized Cortex at ./.cortex
#   config: ./.cortex/config.toml (created)
#   store source: default
#   default Mind: self (created)
#   auth keys: generated reader + writer tokens

$ cortex mind remember self "We use TypeScript and Supabase."
# Mind `self` remembered:
#   We use TypeScript and Supabase.
#   branch main · 3 nodes · 0 edges
#   no persisted mounts to refresh.

$ cortex mind compose self --to codex --task "product strategy"
# Mind `self` → Codex
#   branch main · 2 routed facts · 0 attached packs included · professional
#
# ## Shared AI Context
# **Tech Stack:** Typescript (0.8), Supabase (0.8)

$ cortex mind mount self --to codex --task "product strategy"
# Mounted Mind `self`:
#   codex        ok  Updated 1 file(s)
#     → ./AGENTS.md
#   total persisted mounts: 1
```

## Install

### 1. pip

```
python3.11 -m pip install cortex-identity
```

### 2. pipx

```
pipx install cortex-identity
```

### 3. From source

```
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[dev]"
```

Verify it worked:

```
cortex --help
# Expected: Cortex — one portable Mind across AI tools.
```

Today Cortex is strongest as a local-first CLI and an operator-managed self-host deployment. It is not a hosted memory cloud.

## Core concepts

Think of Cortex as Git-style state management for the part of AI work you keep rebuilding: the memory itself.

| Concept | Plain-English definition |
| --- | --- |
| Mind | Your named memory context: identity, preferences, attached Brainpacks, mounts, and runtime slices. |
| Memory commit | A saved graph snapshot you can diff, review, blame, and restore later. |
| Branch | A separate line of memory history so a client, experiment, or migration does not leak into main. |
| Brainpack | A compiled specialist knowledge pack you can attach to a Mind or mount directly into tools. |
| Portability | Writing the right context slice to each tool instead of copying one blob everywhere. |
| Export / import | Turning raw chats into Cortex graphs, or turning Cortex graphs into target-specific files and bundles. |

## One graph. Four outputs. No copy-paste.

```
$ cortex audience apply-template --mind project --template executive
$ cortex audience apply-template --mind project --template attorney
$ cortex audience apply-template --mind project --template onboarding
$ cortex audience apply-template --mind project --template audit
```

| Template | Disclosure | Provenance | Contested facts |
| --- | --- | --- | --- |
| executive | Summary only | Off | Hidden |
| attorney | Full lineage | On | Flagged |
| onboarding | Current state | Off | Hidden |
| audit | Complete graph | On | Included |

Custom policy:

```
$ cortex audience add --mind project \
  --audience-id counsel \
  --allowed-node-types "decision,milestone,contract" \
  --blocked-node-types "credential,personal" \
  --output-format report \
  --include-provenance true
```

## Command reference

### Memory operations

`$ cortex init`
→ Create or reuse `.cortex`, write `config.toml`, and create the default `self` Mind.
→ Most useful flag: `--mind` if you want a different default Mind id on day one.

`$ cortex mind remember self "We use TypeScript and Supabase."`
→ Add one durable fact or preference directly to a Mind.
→ Most useful flag: `--message` if you want the graph update to carry an explicit commit message.

`$ cortex pack init ai-memory --description "Portable AI memory research"`
→ Create a Brainpack skeleton under `.cortex/packs/ai-memory/`.
→ Most useful flag: `--owner` if the pack belongs to a specific person or team.

`$ cortex pack ingest ai-memory docs/ --recurse`
→ Copy or reference raw source material into a Brainpack.
→ Most useful flag: `--type note` when auto-detection guesses the wrong source type.

`$ cortex pack compile ai-memory --suggest-questions`
→ Compile a Brainpack into wiki pages, graph data, claims, unknowns, and artifacts.
→ Most useful flag: `--suggest-questions` to surface the gaps the pack still cannot answer.

`$ cortex commit context.json -m "Initial memory snapshot"`
→ Save a graph snapshot into the version store as an immutable commit.
→ Most useful flag: `--source` when you want the commit labeled as `merge`, `manual`, or `extraction`.

`$ cortex log --limit 10`
→ Show recent version history for the current branch.
→ Most useful flag: `--all` when you want global history instead of branch ancestry only.

`$ cortex diff 65fc26ac ddccb0de`
→ Compare two stored versions and see structural plus semantic change summaries.
→ Most useful flag: `--format json` if you want to pipe the diff into automation.

`$ cortex rollback context.json --at 2026-04-10T14:30:00Z`
→ Restore a graph file to the latest stored version at or before a timestamp.
→ Most useful flag: `--to` when you already know the exact version id you want back.

### Branching

`$ cortex mind init acme --kind project --label "ACME rollout"`
→ Create a separate Mind for a client, project, or agent instead of piling everything into `self`.
→ Most useful flag: `--default-policy` when this Mind should use a stricter disclosure policy than the default.

`$ cortex branch client/acme --switch`
→ Create a new memory branch and move to it immediately.
→ Most useful flag: `--from main` when the new branch should start from a ref other than `HEAD`.

`$ cortex switch main`
→ Move the active version store back to another branch.
→ Most useful flag: `-c` when you want `switch` to create the branch if it does not exist yet.

`$ cortex merge client/acme --dry-run`
→ Preview what would happen if you merged another branch into the current branch.
→ Most useful flag: `--conflicts` when you want to inspect pending conflicts without attempting a new merge.

`$ cortex review --against main`
→ Review the current branch or a graph file against a baseline ref before you merge it.
→ Most useful flag: `--fail-on blocking,contradictions` to make review failures explicit in CI.

### Portability

`$ cortex switch --from chatgpt-export.zip --to claude --output portable`
→ Convert one tool's export into another tool's import-ready context files.
→ Most useful flag: `--input-format openai` if auto-detection guesses the wrong source format.

`$ cortex portable notes.txt --input-format text --to claude-code codex --project .`
→ Extract context from a raw source and write target-specific files for multiple tools.
→ Most useful flag: `--max-chars` when you need tighter context windows for instruction files.

`$ cortex import context.json --to claude --output portable`
→ Turn an existing Cortex graph into target-specific artifacts without re-extracting it first.
→ Most useful flag: `--dry-run` to see what would be written before touching the filesystem.

`$ cortex sync --smart --project .`
→ Refresh already-ingested runtime context using the router instead of copying one giant block everywhere.
→ Most useful flag: `--policy technical` when coding tools should receive a tighter disclosure slice.

`$ cortex mind compose self --to codex --task "incident follow-up"`
→ Preview the exact runtime slice a Mind would send to a target for a specific task.
→ Most useful flag: `--smart` to let Cortex choose a tighter routed slice for that target.

`$ cortex mind mount self --to codex cursor claude-code --task "incident follow-up"`
→ Materialize a Mind into one or more local tools.
→ Most useful flag: `--project .` when the target uses project-scoped files such as `AGENTS.md`.

`$ cortex connect codex --install --project .`
→ Install Cortex MCP and runtime wiring for Codex before you mount a Mind into it.
→ Most useful flag: `--check` when you want readiness diagnostics without writing config.

`$ cortex connect manus --check`
→ Validate the local Manus bridge setup, auth shape, and expected HTTPS endpoint.
→ Most useful flag: `--url https://your-host.example/mcp` once you have a public bridge endpoint.

`$ cortex serve manus --config .cortex/config.toml --host 127.0.0.1 --port 8790`
→ Run the Manus-friendly hosted MCP bridge locally so a tunnel or reverse proxy can expose it.
→ Most useful flag: `--check` before you bind the process for real.

`$ cortex pack export ai-memory --output dist/ai-memory.brainpack.zip`
→ Export a compiled Brainpack as a portable bundle archive.
→ Most useful flag: `--no-verify` only when you are deliberately skipping the post-write bundle verification step.

`$ cortex pack import dist/ai-memory.brainpack.zip`
→ Import a Brainpack bundle into the local store.
→ Most useful flag: `--store-dir ~/.cortex` when you are importing into a different Cortex store.

### Agent automation

The conflict monitor runs in the background. It detects when two sources assert contradictory facts, proposes resolutions ranked by confidence and recency, auto-resolves low-severity conflicts, and queues critical conflicts for human review.

```
$ cortex agent monitor --interval 300
  Monitoring compliance-kb...
  [09:14:32] Conflict detected — HIGH severity
    Fact: "Data retention: 30 days"  source: policy_v2
    Fact: "Data retention: 90 days"  source: policy_v3
    Candidate resolutions:
      1. Accept policy_v3 (newer, confidence 0.91)
      2. Accept policy_v2 (older, confidence 0.84)
      3. Flag for manual review
    Queued for review. Run: cortex review pending --mind compliance-kb
```

The context dispatcher watches for trigger events and compiles updated context packs automatically — no prompt required.

```
$ cortex agent compile --mind personal --output cv
  Identifying professional subgraph...
  Pulling: employment, skills, publications, certifications
  Flagging gaps: 1 employment period unverified
  Output: ./output/cv_20260413.md
          ./output/cv_20260413.json
```

```
$ cortex agent schedule --mind personal --audience attorney \
  --cron "0 9 * * 1" --output brief
  Scheduled: every Monday 09:00
  Audience: attorney (full lineage, contested facts on)
  Delivery: ./output/
```

`$ cortex agent monitor --interval 300`
→ Run the autonomous conflict monitor loop on a polling interval so Cortex keeps checking for contradictory facts in the background.
→ Most useful flag: `--once` when you want one detection cycle for CI, cron, or smoke checks instead of a long-running loop.

`$ cortex agent compile --mind personal --output cv`
→ Compile an audience-specific artifact from a Mind without waiting for an external prompt.
→ Most useful flag: `--audience recruiter` when the same Mind needs a different disclosure slice or delivery tone.

`$ cortex agent dispatch --event PROJECT_STAGE_CHANGED --payload '{"project_id":"alpha","old_stage":"build","new_stage":"launch","mind_id":"project_alpha"}'`
→ Inject one runtime event into the dispatcher so Cortex applies the matching compilation rule immediately.
→ Most useful flag: `--output-dir ./output` when you want artifacts written to a specific directory instead of the default runtime location.

`$ cortex agent schedule --mind personal --audience attorney --cron "0 9 * * 1" --output brief`
→ Register a recurring dispatch that compiles the same audience slice on a schedule.
→ Most useful flag: `--delivery webhook` when the result should be pushed to another service instead of written locally.

`$ cortex agent status`
→ Show active monitor state, queued conflicts awaiting review, and registered dispatch schedules.
→ Most useful flag: `--format json` when another runtime or dashboard needs the state programmatically.

### Inspection

`$ cortex doctor`
→ Check store, config, runtime mode, bind scope, and repairable drift in the current workspace.
→ Most useful flag: `--fix --dry-run` when you want to preview repairs before Cortex writes anything.

`$ cortex mind status self`
→ Show a Mind's manifest, branch, policy, attachments, and mounts.
→ Most useful flag: `--format json` if another tool needs to inspect the state programmatically.

`$ cortex pack status ai-memory`
→ Show Brainpack source counts, compile state, artifacts, and lint summary.
→ Most useful flag: `--format json` when you want machine-readable pack health in CI.

`$ cortex scan --project .`
→ Inspect local tool files and exports without mutating the store.
→ Most useful flag: `--search-root ~/Downloads` when the export you want sits outside the project directory.

`$ cortex status --project .`
→ Show which configured tools are stale or missing routed context.
→ Most useful flag: `--format json` when you want to gate a workflow on fresh mounts.

`$ cortex memory show context.json --tag technical_expertise`
→ Inspect nodes from a graph file without opening the JSON by hand.
→ Most useful flag: `--label "Supabase"` when you want to inspect one exact node.

`$ cortex query context.json --search "Supabase" --limit 5`
→ Search a graph across labels, aliases, and descriptions.
→ Most useful flag: `--dsl` when you want the query language instead of keyword search.

`$ cortex history context.json --label "Supabase" --limit 10`
→ Walk the receipt timeline for one node across stored versions.
→ Most useful flag: `--source extraction` when you want receipts from one source type only.

`$ cortex blame context.json --label "Supabase" --limit 10`
→ Trace a node back to the commit lineage that introduced it.
→ Most useful flag: `--ref main` when you want blame against a specific branch ancestry.

### Governance

`$ cortex verify signed-export.json`
→ Verify a signed export file before you trust or import it.
→ Most useful flag: none; this command is intentionally small and does one thing.

`$ cortex governance check --actor agent/coder --action write --namespace main`
→ Ask whether a given actor may perform an action in a namespace right now.
→ Most useful flag: `--against main` when approval gating depends on semantic diff against a baseline.

`$ cortex governance allow protect-main --action write --namespace main --require-approval`
→ Create or replace a governance rule for a namespace or branch.
→ Most useful flag: `--approval-below-confidence 0.75` when low-confidence writes should require review.

`$ cortex remote push origin --branch main`
→ Push a local memory branch to a configured remote store.
→ Most useful flag: `--to-branch release/main` when the remote branch name should differ from the local one.

`$ cortex remote pull origin --branch main --into-branch remotes/origin/main`
→ Pull a remote branch into a local branch for review or merge.
→ Most useful flag: `--switch` when you want to move to the updated local branch immediately.

`$ cortex backup export --store-dir .cortex --output backups/pre-change.zip`
→ Create a verified archive of the current store before a risky change.
→ Most useful flag: `--no-verify` only for controlled debug cases where you do not want the post-write verification step.

`$ cortex backup verify backups/pre-change.zip`
→ Confirm a backup archive is valid before you restore it.
→ Most useful flag: none; verification should stay explicit and simple.

## Real workflows

### Workflow A: I'm switching from ChatGPT to Claude mid-project

```
$ cortex switch --from chatgpt-export.zip --to claude --output portable --dry-run
# Portable switch ready: chatgpt -> claude
#   claude: portable/claude/claude_preferences.txt, portable/claude/claude_memories.json [dry-run]

$ cortex switch --from chatgpt-export.zip --to claude --output portable
# Portable switch ready: chatgpt -> claude
#   claude: portable/claude/claude_preferences.txt, portable/claude/claude_memories.json [created]
```

### Workflow B: I want a separate memory context for a client engagement

```
$ cortex init
# Initialized Cortex at ./.cortex
#   default Mind: self (created)

$ cortex mind init acme --kind project --label "ACME rollout"
# Created Mind `acme` at ./.cortex/minds/acme

$ cortex mind remember acme "Infrastructure must stay in us-east-1 and meet SOC 2."
# Mind `acme` remembered:
#   Infrastructure must stay in us-east-1 and meet SOC 2.
#   branch main · 1 nodes · 0 edges
#   no persisted mounts to refresh.

$ cortex mind status acme
# Mind `acme`
#   ACME rollout · project
#   branch main · 0 attached Brainpacks · 0 attached pack mounts · 0 direct mind mounts · professional · non-default
#   graph ref: refs/minds/acme/branches/main

$ cortex mind mount acme --to codex --task "client handoff"
# Mounted Mind `acme`:
#   codex        ok  Updated 0 file(s)
#   total persisted mounts: 1
```

### Workflow C: Something went wrong — I need to roll back my AI memory to yesterday

```
$ cortex extract notes.txt --output context.json
# Loading: notes.txt
# Format: text
# Extracted 2 topics across 2 categories
# Saved to: context.json

$ cortex commit context.json -m "Initial memory snapshot"
# Committed: 65fc26accf0373d4d8990f24341c9263
#   Branch: main
#   Message: Initial memory snapshot

$ cortex commit context.json -m "Expand stack memory"
# Committed: ddccb0dea118f1dbb0d415909d9efea5
#   Branch: main
#   Message: Expand stack memory

$ cortex log --limit 2
# * ddccb0dea118f1dbb0d415909d9efea5  2026-04-11T05:28:02+00:00  [manual] (main)
#     Expand stack memory
# * 65fc26accf0373d4d8990f24341c9263  2026-04-11T05:28:01+00:00  [manual] (main)
#     Initial memory snapshot

$ cortex rollback context.json --to 65fc26ac
# Rolled back main to aa0af1625b548afc315bbf32c17e15c1 as new commit aa0af1625b548afc315bbf32c17e15c1.
#   Wrote restored graph to context.json
```

## Why Cortex instead of ...

| Feature | Cortex | ChatGPT Memory | Claude Projects | Mem0 |
| --- | --- | --- | --- | --- |
| Portability across platforms | ✓ | ✗ | ✗ | ~ |
| Version control / rollback | ✓ | ~ | ✗ | ✗ |
| CLI-native workflow | ✓ | ✗ | ✗ | ~ |
| Open source | ✓ | ✗ | ✗ | ✓ |
| Local-first / no vendor lock-in | ✓ | ✗ | ✗ | ~ |
| Exportable format | ✓ | ✗ | ✗ | ✓ |

## Architecture in one diagram

```text
                raw chats / notes / exports / tool files
     ┌──────────────┬──────────────┬──────────────┬──────────────┐
     │ ChatGPT ZIP  │ Claude files │ Local notes  │ Repo context  │
     └──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┘
            │              │              │              │
            └──────────────┴──── extract / portable / switch ───────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │   Cortex commit graph    │
                              │   cortex.graph           │
                              │   commit / diff / merge  │
                              │   blame / history        │
                              └─────────────┬────────────┘
                                            │
                           ┌────────────────┼────────────────┐
                           │                │                │
                           ▼                ▼                ▼
                  ┌────────────────┐ ┌──────────────┐ ┌──────────────┐
                  │ Minds          │ │ Brainpacks   │ │ Claims /     │
                  │ minds/         │ │ packs/       │ │ versions /   │
                  │ compose/mount  │ │ compile/query│ │ backups      │
                  └────────┬───────┘ └──────┬───────┘ └──────┬───────┘
                           │                │                │
                           └────────────┬───┴────────────────┘
                                        │
                                        ▼
                              ┌──────────────────────────┐
                              │      Local store         │
                              │        .cortex/          │
                              │  filesystem or SQLite    │
                              └─────────────┬────────────┘
                                            │
                    ┌───────────────────────┼────────────────────────┐
                    │                       │                        │
                    ▼                       ▼                        ▼
          ┌────────────────┐    ┌────────────────────┐    ┌────────────────┐
          │ direct mounts  │    │ runtime surfaces   │    │ import/export  │
          │ AGENTS.md      │    │ serve api / mcp    │    │ Claude files   │
          │ CLAUDE.md      │    │ serve manus / ui   │    │ ChatGPT files  │
          │ Cursor rules   │    │ cortexd / MCP      │    │ Brainpack ZIPs │
          │ Hermes memory  │    │ bridge + local UI  │    │ signed exports │
          └────────────────┘    └────────────────────┘    └────────────────┘
```

## Contributing

Cortex is for developers who already feel the pain of rebuilt AI context: people switching between ChatGPT, Claude, Codex, Cursor, Hermes, local MCP tools, or self-hosted agents and wanting one memory layer they can inspect, diff, and control. If that problem bothers you enough that you keep sketching your own solution on napkins, you will probably care about this repo.

You can get a dev environment up in under five commands:

```
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[dev]"
ruff check cortex tests
python3.11 -m pytest tests -q --tb=short
```

There are no public open issues at the moment. The highest-leverage roadmap work is already named in the repo: `pack-native Q&A loops`, `bundle-aware UI flows`, and `clean-machine install-path verification for runtime adapters and self-host surfaces`. If you want to help, start there, or tighten a rough edge in `docs/SELF_HOSTING.md`, `docs/OPERATIONS.md`, or the first-run CLI paths.

## Footer

License: [MIT](LICENSE)
PyPI: [cortex-identity](https://pypi.org/project/cortex-identity/)
Issues: [GitHub Issues](https://github.com/Junebugg1214/Cortex-AI/issues)

If this saves you one rebuild of context, it already paid for itself.
