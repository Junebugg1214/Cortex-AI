# Brainpacks

Brainpacks are the **specialist cognition subsystem** for a Cortex Mind.

They are local-first domain packs: raw source files go in, and Cortex compiles them into a small wiki, a graph, claim candidates, open questions, durable answer artifacts, lint reports, portable bundles, and direct runtime mounts.

The important Mind-first framing is:

- a Brainpack can stand alone while you build and query it
- once attached to a Mind, it becomes specialist cognition that Cortex can compose in by target and task

## What a Brainpack Looks Like

Every Brainpack lives under:

```text
.cortex/packs/<name>/
  manifest.toml
  raw/
  wiki/
  graph/
  claims/
  unknowns/
  artifacts/
  indexes/
```

What Cortex writes today:

- `wiki/` gets an index plus one source article per readable ingested source
- `graph/brainpack.graph.json` gets the compiled Cortex graph
- `claims/claims.json` gets claim candidates derived from the compiled graph
- `unknowns/open_questions.json` gets suggested open questions and coverage gaps
- `artifacts/` gets generated notes, reports, or slides created by `pack ask`
- `indexes/lint.json` gets the latest Brainpack integrity report from `pack lint`
- `indexes/` stores source inventory and compile metadata

## Mind-First Quickstart

Create and compile the Brainpack:

```bash
cortex pack init ai-memory --description "Portable AI memory research" --owner marc
cortex pack ingest ai-memory ~/Downloads/papers ~/notes/ai-memory --recurse
cortex pack compile ai-memory --suggest-questions
cortex pack query ai-memory "portable agent memory"
cortex pack ask ai-memory "What does this pack say about portable agent memory?" --output report
cortex pack lint ai-memory
```

Attach it to a Mind:

```bash
cortex mind attach-pack marc ai-memory --always-on --target hermes --target codex --task-term memory
```

Preview or materialize it through the Mind:

```bash
cortex mind compose marc --to hermes --task "memory support"
cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"
```

Export the compiled Brainpack as a portable bundle:

```bash
cortex pack export ai-memory --output ./dist/ai-memory.brainpack.zip
```

Import that bundle into another Cortex store:

```bash
cortex pack import ./dist/ai-memory.brainpack.zip --store-dir ~/.cortex
```

If the bundle name would collide locally, import it under a new name:

```bash
cortex pack import ./dist/ai-memory.brainpack.zip --store-dir ~/.cortex --as ai-memory-copy
```

## Commands

| Command | What it does |
| --- | --- |
| `cortex pack init ai-memory --description "Portable AI memory research" --owner marc` | Creates a new Brainpack skeleton and manifest under `.cortex/packs/ai-memory/`. |
| `cortex pack list` | Lists local Brainpacks in the current Cortex store. |
| `cortex pack ingest ai-memory ~/Downloads/papers ~/notes/ai-memory --recurse` | Copies or references local files into the Brainpack source inventory. |
| `cortex pack compile ai-memory --suggest-questions` | Compiles readable sources into a wiki, graph, claims, and suggested unknowns. |
| `cortex pack status ai-memory` | Shows source counts, graph size, compile state, artifact counts, lint state, and mount state. |
| `cortex pack context ai-memory --target hermes --smart` | Renders a routed Brainpack slice for a specific target runtime. |
| `cortex pack query ai-memory "portable agent memory"` | Searches concepts, claims, wiki pages, unknowns, and existing artifacts. |
| `cortex pack ask ai-memory "What does this pack say about portable agent memory?" --output report` | Answers against the compiled pack and writes the result back as a durable artifact. |
| `cortex pack lint ai-memory` | Runs integrity checks for contradictions, duplicates, weak claims, thin articles, and graph health. |
| `cortex pack mount ai-memory --to hermes openclaw codex cursor claude-code --project . --smart` | Mounts the compiled Brainpack directly into supported runtimes and tools, without attaching it to a Mind first. |
| `cortex pack export ai-memory --output ./dist/ai-memory.brainpack.zip` | Exports a portable Brainpack bundle archive. |
| `cortex pack import ./dist/ai-memory.brainpack.zip --store-dir ~/.cortex --as ai-memory-copy` | Imports a Brainpack bundle into another Cortex store under a chosen name. |
| `cortex mind attach-pack marc ai-memory --always-on --target hermes --task-term memory` | Attaches the Brainpack to a Mind so it can be composed selectively or always-on at runtime. |
| `cortex mind compose marc --to hermes --task "memory support"` | Shows what the Mind plus attached Brainpacks will actually look like for a given runtime and task. |
| `cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"` | Materializes the composed Mind, including attached Brainpacks, into supported runtimes and tools. |

## Direct `pack mount`

`pack mount` is still useful when you want to mount a specialist pack directly without making it part of a larger Mind first.

What this does today:

- Hermes gets pack-derived `USER.md`, `MEMORY.md`, and managed MCP wiring
- Codex, Cursor, and Claude Code get the routed Brainpack slice installed into their native instruction files
- OpenClaw gets a plugin-readable Brainpack mount registry so the OpenClaw Cortex plugin injects the pack live on each turn

## MCP Support

The Brainpacks MCP surface is available now:

- `pack_list`
- `pack_status`
- `pack_compile`
- `pack_context`
- `pack_query`
- `pack_ask`
- `pack_lint`
- `pack_mount`
- `pack_export`
- `pack_import`

That means MCP-capable runtimes can already see compiled packs and ask Cortex for a routed Brainpack context slice.

## UI Support

Open the local UI with:

```bash
cortex ui
```

The Brainpacks panel exposes:

- Sources
- Concepts
- Claims
- Unknowns
- Artifacts

## What Brainpacks Are Good For Today

- building a local specialist pack from notes, markdown, repos, and text files
- generating a small wiki and graph that persist outside a single chat session
- querying the compiled pack and turning the answer into durable notes, reports, or slide drafts
- running integrity checks for contradictions, duplicates, orphan concepts, weak claims, and thin source pages
- attaching specialist cognition to a Mind for target-aware runtime composition
- mounting a compiled Brainpack directly into Hermes, OpenClaw, Codex, Cursor, Claude Code, and other portability targets
- exporting a portable bundle that carries the current pack, compiled outputs, and materialized reference sources when possible
- importing that bundle into another Cortex store without rebuilding the pack from scratch

## What Is Next

The current release is the Brainpacks query, artifact, lint, mount, bundle, and UI loop. The next major steps are:

- richer artifact filing and pack-native Q&A loops
- deeper bundle-aware UI flows
