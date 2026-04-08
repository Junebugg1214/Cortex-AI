# Cortex Minds

A **Mind** is the top-level object in Cortex.

It is the thing that persists across tools, composes specialist Brainpacks, carries version history, and gets mounted into runtimes like Hermes, OpenClaw, Codex, Cursor, and Claude Code.

## The Model

Think of a Mind as one portable brain-state with four layers:

- **core state**: identity, preferences, relationships, technical context, and durable memory
- **attached Brainpacks**: specialist domain modules that Cortex can activate by target and task
- **version history**: commit, branch, review, diff, merge, blame, and rollback over the underlying graph
- **runtime mounts**: materialized slices for Hermes, OpenClaw, Codex, Cursor, Claude Code, and other targets

That makes the rest of Cortex easier to understand:

- **Portable AI** feeds and syncs a Mind's core state
- **Brainpacks** are attachable specialist cognition on a Mind
- **Git for AI Memory** is the version and governance layer for a Mind

## Quickstart

```bash
cortex mind init marc --kind person --owner marc
cortex mind default marc
cortex scan --project .
cortex mind ingest marc --from-detected chatgpt claude claude-code codex cursor hermes --project .
cortex mind remember marc "I prefer concise, implementation-first responses."
cortex pack init ai-memory --description "Portable AI memory research" --owner marc
cortex pack ingest ai-memory ~/Downloads/papers ~/notes/ai-memory --recurse
cortex pack compile ai-memory --suggest-questions
cortex mind attach-pack marc ai-memory --always-on --target hermes --target codex --task-term memory
cortex mind compose marc --to chatgpt --task "memory routing"
cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"
```

What happens in that flow:

1. `mind init` creates the persistent Mind object.
2. `mind default` makes classic portability commands route through that Mind.
3. `mind ingest` adopts detected local AI context into the Mind's core graph.
4. `mind remember` teaches the Mind one new fact or preference directly.
5. `pack init/ingest/compile` creates a specialist Brainpack.
6. `mind attach-pack` connects that Brainpack to the Mind with activation rules.
7. `mind compose` previews what the Mind plus attached Brainpacks will look like for a target and task.
8. `mind mount` materializes that Mind into supported runtimes and tools.

## Commands

| Command | What it does |
| --- | --- |
| `cortex mind init marc --kind person --owner marc` | Creates a new Mind under `.cortex/minds/marc/` with manifest, core-state, branch, policy, attachment, and mount scaffolding. |
| `cortex mind default marc` | Marks one Mind as the default compatibility target so classic commands like `portable`, `remember`, and `sync --smart` can route through it. |
| `cortex mind list` | Lists local Minds in the current Cortex store. |
| `cortex mind status marc` | Shows the Mind manifest, core-state ref, current branch, disclosure policy, attached Brainpacks, and persisted mounts. |
| `cortex mind ingest marc --from-detected ... --project .` | Adopts detected local context directly into the Mind's core graph and commits it onto the Mind's current branch. |
| `cortex mind remember marc "..."` | Adds one new fact or preference directly to the Mind's core graph and refreshes persisted mounts from the updated state. |
| `cortex mind attach-pack marc ai-memory --always-on --target hermes --task-term memory` | Attaches an existing Brainpack to a Mind and records activation metadata for future composition. |
| `cortex mind detach-pack marc ai-memory` | Detaches a Brainpack from a Mind without deleting the Brainpack itself. |
| `cortex mind compose marc --to chatgpt --task "memory routing"` | Composes a target-aware runtime slice from the Mind's current base graph plus any attached Brainpacks that match the target and task. |
| `cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"` | Materializes the composed Mind into supported runtimes and tools. |
| `cortex mind mounts marc` | Lists the persisted mount records for a Mind, including runtime-target metadata and file paths. |

## How the Subsystems Fit

### Portable AI

Portable AI is how a Mind learns and gets synchronized.

- `scan` tells you what context already exists on disk
- `mind ingest` adopts detected local context into a Mind
- `mind remember` teaches the Mind one new thing directly
- `portable`, `remember`, and `sync --smart` still work as compatibility flows
- if a default Mind is configured, those classic flows route through that Mind

### Brainpacks

Brainpacks are specialist modules that a Mind can mount temporarily or always-on.

- compile a Brainpack from raw source material
- attach it to a Mind with target and task filters
- preview composition with `mind compose`
- materialize it with `mind mount`

### Git for AI Memory

The underlying graph is still versioned.

- `commit`, `branch`, `switch`, `review`, `diff`, `merge`, `log`, `blame`, `history`, and `rollback` remain the graph-level safety tools
- the Mind uses those refs as its durable core-state history
- that means you can mutate and mount a Mind without treating memory like an unreviewed blob

## Compatibility Layer

Mind-first is the recommended mental model, but Cortex keeps the old flows working:

- if you do **not** configure a default Mind, classic `portable`, `remember`, and `sync --smart` use the standalone portability graph
- if you **do** configure a default Mind with `cortex mind default <name>`, those same commands route through that Mind behind the scenes

That gives you a clean migration path from "portable graph" to "portable Mind" without breaking existing workflows.
