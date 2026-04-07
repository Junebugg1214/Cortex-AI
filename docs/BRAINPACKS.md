# Brainpacks

Brainpacks are Cortex's local-first domain packs: raw source files go in, and Cortex compiles them into a small wiki, a graph, claim candidates, open questions, durable answer artifacts, and lint reports that any agent can consume.

This release gives you the native pack layout, ingestion, compilation, status, routed context rendering, direct pack mounts into Hermes/OpenClaw/Codex/Cursor/Claude Code and other portability targets, `pack query`, `pack ask` with artifact write-back, `pack lint` for ongoing pack integrity checks, Brainpack bundle export/import, and a dedicated Brainpacks view inside `cortex ui`.

## What a Brainpack looks like

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

## Quickstart

Create a pack:

```bash
cortex pack init ai-memory --description "Portable AI memory research" --owner marc
```

Ingest local files or directories:

```bash
cortex pack ingest ai-memory ~/Downloads/papers ~/notes/ai-memory --recurse
```

Compile the pack:

```bash
cortex pack compile ai-memory --suggest-questions
```

Inspect it:

```bash
cortex pack status ai-memory
cortex pack list
```

Render a routed slice for a target runtime:

```bash
cortex pack context ai-memory --target hermes --smart
```

Search the compiled pack:

```bash
cortex pack query ai-memory "portable agent memory"
```

Ask a question and save the answer back into the pack:

```bash
cortex pack ask ai-memory "What does this pack say about portable agent memory?" --output report
```

Run integrity checks over the pack:

```bash
cortex pack lint ai-memory
```

Mount the compiled pack directly into live runtimes and coding tools:

```bash
cortex pack mount ai-memory --to hermes openclaw codex cursor claude-code --project . --smart
```

What this does:

- Hermes gets pack-derived `USER.md`, `MEMORY.md`, and managed MCP wiring
- Codex, Cursor, and Claude Code get the routed Brainpack slice installed into their native instruction files
- OpenClaw gets a plugin-readable Brainpack mount registry so the OpenClaw Cortex plugin injects the pack live on each turn

Export a portable bundle:

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

## MCP support

The first Brainpacks MCP surface is available now:
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

## UI support

Open the local UI with:

```bash
cortex ui
```

The Brainpacks panel now exposes:
- Sources
- Concepts
- Claims
- Unknowns
- Artifacts

## What this is good for today

- building a local specialist pack from notes, markdown, repos, and text files
- generating a small wiki and graph that persist outside a single chat session
- querying the compiled pack and turning the answer into durable notes, reports, or slide drafts
- running integrity checks for contradictions, duplicates, orphan concepts, weak claims, and thin source pages
- mounting a compiled Brainpack directly into Hermes, OpenClaw, Codex, Cursor, Claude Code, and other portability targets
- exporting a portable bundle that carries the current pack, compiled outputs, and materialized reference sources when possible
- importing that bundle into another Cortex store without rebuilding the pack from scratch
- creating a durable foundation for richer artifact workflows

## What is next

The current release is the Brainpacks query, artifact, lint, mount, bundle, and UI loop. The next major steps are:
- richer artifact filing and pack-native Q&A loops
- deeper bundle-aware UI flows
