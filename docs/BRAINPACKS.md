# Brainpacks

Brainpacks are Cortex's local-first domain packs: raw source files go in, and Cortex compiles them into a small wiki, a graph, claim candidates, open questions, and durable answer artifacts that any agent can consume.

This release gives you the native pack layout, ingestion, compilation, status, routed context rendering, `pack query`, and `pack ask` with artifact write-back. It does **not** yet include `pack lint`, pack export/import bundles, or a dedicated UI surface.

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

## MCP support

The first Brainpacks MCP surface is available now:
- `pack_list`
- `pack_status`
- `pack_compile`
- `pack_context`
- `pack_query`
- `pack_ask`

That means MCP-capable runtimes can already see compiled packs and ask Cortex for a routed Brainpack context slice.

## What this is good for today

- building a local specialist pack from notes, markdown, repos, and text files
- generating a small wiki and graph that persist outside a single chat session
- querying the compiled pack and turning the answer into durable notes, reports, or slide drafts
- mounting the compiled pack into Hermes, Codex, Cursor, Claude Code, or other Cortex portability targets
- creating a durable foundation for future `lint`, bundle export/import, and richer artifact workflows

## What is next

The current release is the Brainpacks query-and-artifact loop. The next major steps are:
- `cortex pack lint`
- export/import bundles
- pack-aware UI views
- richer artifact filing and pack-native Q&A loops
