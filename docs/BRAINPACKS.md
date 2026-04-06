# Brainpacks

Brainpacks are Cortex's local-first domain packs: raw source files go in, and Cortex compiles them into a small wiki, a graph, claim candidates, and open questions that any agent can consume.

This first Brainpacks release is intentionally foundational. It gives you the native pack layout, ingestion, compilation, status, and routed context rendering. It does **not** yet include `pack ask`, `pack lint`, pack export/import bundles, or a dedicated UI surface.

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

## MCP support

The first Brainpacks MCP surface is available now:
- `pack_list`
- `pack_status`
- `pack_compile`
- `pack_context`

That means MCP-capable runtimes can already see compiled packs and ask Cortex for a routed Brainpack context slice.

## What this is good for today

- building a local specialist pack from notes, markdown, repos, and text files
- generating a small wiki and graph that persist outside a single chat session
- mounting the compiled pack into Hermes, Codex, Cursor, Claude Code, or other Cortex portability targets
- creating a durable foundation for future `ask`, `lint`, and artifact workflows

## What is next

The current release is the Brainpacks foundation. The next major steps are:
- `cortex pack ask`
- `cortex pack lint`
- export/import bundles
- pack-aware UI views
- artifact filing and pack-native Q&A loops
