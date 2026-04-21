# Cortex

**Git for AI memory. Local-first, MCP-native.**

Cortex is a local memory layer for AI agents. It gives you a user-owned graph on disk with Git-like commits, branches, merge, blame, and source-backed retraction — and an MCP server any agent can read from.

No Cortex cloud. No Cortex API key. Your agent keeps using its own LLM; Cortex is just where the memory lives. Optional model-based extraction uses your own provider key.

**Works with:** Claude Code · Cursor · Codex · Windsurf · Copilot · Gemini CLI · ChatGPT · Grok · **[OpenClaw](docs/OPENCLAW_QUICKSTART.md)** · **[Hermes](docs/HERMES_QUICKSTART.md)**

```bash
pip install cortex-identity
cortex init
cortex remember "We use TypeScript and Supabase"
cortex sync --smart --project .   # fans out to every tool you use
```

Demos: [retraction](demos/retraction.mp4) · [portability](demos/portability.mp4) · [audience](demos/audience.mp4) (also available as [asciinema casts](demos/README_DEMOS.md))

![portability](demos/portability.svg)

---

Local-first. No Cortex cloud, no Cortex key. Integrate over MCP, local REST, or SDK. Model extraction is opt-in and uses your own provider key.

This README is intentionally implementation-aligned. Examples use supported commands and supported input formats on a fresh install.

## Install

```bash
python3.11 -m pip install cortex-identity
cortex --help
```

For development from source:

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[dev]"
cortex --help
```

## Quickstart: create a local Mind and mount it into Codex

```bash
mkdir cortex-demo
cd cortex-demo
cortex init
cortex mind remember self "We use TypeScript and Supabase."
cortex mind compose self --to codex --task "product strategy"
cortex mind mount self --to codex --project . --task "product strategy"
```

`cortex mind mount` writes a Cortex-managed block into `AGENTS.md` while preserving content outside the Cortex markers.

Use `cortex mount watch` when you have a graph file you want to keep mounted after changes. An example appears in the extraction section below.

## Extraction

Create a supported source file:

```bash
cat > policy_v3.md <<'EOF_POLICY'
# Policy v3
Data retention is 90 days.
We use Python, TypeScript, and Supabase.
Please keep compliance summaries concise.
EOF_POLICY
```

Extract it into a Cortex graph:

```bash
cortex extract run policy_v3.md --output policy_v3.context.json
cortex mount watch --project . --graph policy_v3.context.json --interval 30 --to codex
```

Default extraction is local and rule-based. Model and hybrid extraction are
available when configured, and all current backends use the typed extraction
contract described in [docs/EXTRACTION.md](docs/EXTRACTION.md).

Model extraction is opt-in:

```bash
export CORTEX_HOT_PATH_BACKEND=model
export CORTEX_ANTHROPIC_API_KEY=sk-ant-...
cortex extract run policy_v3.md --output policy_v3.context.json
```

PDFs require pre-conversion to a supported text or JSON format before ingest. See
[docs/INGEST_FORMATS.md](docs/INGEST_FORMATS.md) for the exact loader catalog,
and [docs/EXTRACTION.md](docs/EXTRACTION.md) for pipeline stages, diagnostics,
replay, evals, and the cost-aware router.

## Versioning workflow

```bash
cortex commit policy_v3.context.json -m "Initial policy memory"
cortex log --limit 5
cortex branch policy-review --switch
cortex commit policy_v3.context.json -m "Review policy context"
cortex branch switch main
cortex merge policy-review --dry-run
```

Cortex stores graph snapshots with refs and branch pointers under `.cortex/`. Recent versions use a Merkle-chained version id that folds ancestry metadata into the commit digest while leaving the graph hash as the content hash.

## Retraction and provenance

Cortex can retract source-backed graph content when nodes and edges carry provenance. The current safe workflow is to inspect source lineage first, then retract with a dry run:

```bash
cortex source list --mind self
```

After `cortex source list` shows a real source id, use `cortex source retract <source-id> --mind self --dry-run` before confirming a retraction. Extraction and merge paths attach provenance for generated nodes so retraction has lineage to follow.

## Portability

Cortex can write target-specific context files and artifacts. Round-trip pull support is narrower than write support.

| Target | Write / mount | Round-trip (pull) |
| --- | --- | --- |
| Claude | ✅ | ✅ |
| Notion | ✅ | ✅ |
| SystemPrompt | ✅ | ✅ |
| Claude Code | ✅ | ⚠ write-only |
| Codex | ✅ | ⚠ write-only |
| Cursor | ✅ | ⚠ write-only |
| Copilot | ✅ | ⚠ write-only |
| Windsurf | ✅ | ⚠ write-only |
| Gemini CLI | ✅ | ⚠ write-only |
| ChatGPT export artifacts | ✅ | ⚠ write-only |
| Grok export artifacts | ✅ | ⚠ write-only |
| Hermes runtime context | ✅ | ⚠ write-only |

Examples:

```bash
cortex sync policy_v3.context.json --to codex --project .
cortex mount watch --project . --graph policy_v3.context.json --to codex cursor
cortex source status --project .
cortex status --project .
```

`cortex sync` and `cortex mount watch` preserve user content outside Cortex marker blocks when writing instruction files.

## Deduplication

Deduplication today uses lexical label similarity plus graph-neighbor overlap. It does not use embeddings. Duplicate candidates are compacted transitively, so if A matches B and B matches C above threshold, all three can collapse into one canonical node even when A and C are below threshold directly.

## Remotes and federation

Remotes today are local-filesystem paths only. Network transport is on the roadmap.

Federation bundles are signed graph exports for cross-instance sharing. Signature verification reports structured failures for malformed bundles, untrusted keys, and invalid signatures.

## Agent runtime

The agent runtime commands are available under the admin namespace:

`$ cortex admin agent monitor --interval 300`

`$ cortex admin agent compile --mind personal --output cv`

`$ cortex admin agent status`

## MCP and local service surfaces

```bash
cortex serve mcp --help
cortex serve --help
cortex admin openapi --help
```

The HTTP server is intended for local or operator-managed deployments. Put it behind a real TLS/auth/rate-limit boundary before exposing it beyond localhost.

## Core commands

| Command | Purpose |
| --- | --- |
| `cortex init` | Initialize `.cortex` and the default Mind |
| `cortex mind remember` | Add a fact or preference to a Mind |
| `cortex mind compose` | Preview a target-specific runtime slice |
| `cortex mind mount` | Write a Mind slice into supported local tool files |
| `cortex mount watch` | Poll a graph and refresh mounted context files |
| `cortex extract run` | Convert supported input files into a Cortex graph |
| `cortex sync` | Propagate context across configured targets |
| `cortex compose` | Render context without writing a persistent mount |
| `cortex commit` | Save a graph snapshot to the version store |
| `cortex branch` | Create or list memory branches |
| `cortex branch switch` | Switch active branch |
| `cortex merge` | Merge another memory branch |
| `cortex diff` | Compare two versions |
| `cortex debug review` | Review a graph or branch before merge |
| `cortex source` | Inspect and retract source lineage from Minds |
| `cortex pack` | Manage Brainpacks |
| `cortex audience` | Manage audience disclosure policies |
| `cortex remote` | Push/pull local-filesystem remotes |
| `cortex verify` | Verify signed exports or store integrity |
| `cortex admin doctor` | Inspect and repair local store/config issues |

Run `cortex COMMAND --help` for the exact flags supported by your installed version.

## Development

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[dev]"
ruff check cortex tests
python3.11 -m pytest tests -q --tb=short
```

## Status

Cortex is production-fit for disciplined local-first and small-team self-hosted workflows. It is not a hosted memory cloud, not a cloud multi-tenant service, and not a default LLM extractor. The strongest current core is versioned graph storage, branch/merge/review, source-backed retraction, local tool mounts, audience filtering, and MCP/local service integration.

## License

MIT. See [LICENSE](LICENSE).
