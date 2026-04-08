[![PyPI](https://img.shields.io/pypi/v/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![Python](https://img.shields.io/pypi/pyversions/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![License](https://img.shields.io/github/license/Junebugg1214/Cortex-AI)](https://github.com/Junebugg1214/Cortex-AI/blob/main/LICENSE)

# Cortex

You use multiple AI tools.  
They all think you're a stranger.  
Cortex fixes that.

Cortex is three things in one local-first system:

1. **Portable AI**: detect, ingest, route, and sync your AI context across Claude, Claude Code, ChatGPT, Codex, Cursor, Copilot, Gemini, Grok, Hermes, and Windsurf.
2. **Brainpacks**: compile source files into mountable domain packs with a wiki, graph, claims, unknowns, artifacts, and direct runtime mounts.
3. **Git for AI Memory**: branch, review, diff, merge, blame, and roll back graph-shaped memory instead of treating context like an unversioned blob.

Humans curate context with the CLI. MCP-capable runtimes fetch their live routed slice over `cortex mcp`.

## Cortex Mind (Preview)

`cortex mind` is the new top-level object that will unify Portable AI, Brainpacks, and Git for AI Memory under one portable, versioned, composable mind.

The first implementation slice ships the foundation:

```bash
cortex mind init marc --kind person --owner marc
cortex mind default marc
cortex mind ingest marc --from-detected chatgpt claude claude-code codex cursor hermes --project .
cortex mind remember marc "I prefer concise, implementation-first responses."
cortex mind attach-pack marc ai-memory --always-on
cortex mind compose marc --to chatgpt --task "memory routing"
cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"
cortex mind mounts marc
cortex mind list
cortex mind status marc
cortex mind detach-pack marc ai-memory
```

Mind foundation commands:

| Command | What it does |
| --- | --- |
| `cortex mind init marc --kind person --owner marc` | Creates a new Mind under `.cortex/minds/marc/` with manifest, core-state, policy, branch, mount, and attachment scaffolding. |
| `cortex mind default marc` | Marks one Mind as the default compatibility target so classic commands like `portable`, `remember`, and `sync --smart` can route through that Mind behind the scenes. |
| `cortex mind ingest marc --from-detected chatgpt claude claude-code codex cursor hermes --project .` | Adopts detected local context directly into the Mind's core graph and commits it onto the Mind's current branch instead of the shared portability canonical graph. |
| `cortex mind remember marc "I prefer concise, implementation-first responses."` | Adds one new fact or preference directly to the Mind's core graph, commits it onto the current Mind branch, and refreshes any persisted Mind mounts from that updated state. |
| `cortex mind attach-pack marc ai-memory --always-on` | Attaches an existing Brainpack to a Mind and records activation metadata for future composition. |
| `cortex mind compose marc --to chatgpt --task "memory routing"` | Composes a target-aware runtime slice from the Mind's current base graph plus any attached Brainpacks that match the target/task. |
| `cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"` | Materializes the composed Mind into direct targets like Hermes/Codex/Cursor/Claude Code and registers it for live OpenClaw runtime composition. |
| `cortex mind mounts marc` | Lists the persisted mount records for a Mind, including runtime-target metadata and file paths. |
| `cortex mind list` | Lists local Minds in the current Cortex store. |
| `cortex mind status marc` | Shows the Mind manifest, graph reference, branch, disclosure policy, attached Brainpacks, and current pack-derived mount metadata. |
| `cortex mind detach-pack marc ai-memory` | Detaches a Brainpack from a Mind without deleting the Brainpack itself. |

## Install

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[server]"
mkdir -p .cortex
cp docs/examples/config.toml .cortex/config.toml
cortex scan --project .
```

What each command does:

| Command | What it does |
| --- | --- |
| `git clone https://github.com/Junebugg1214/Cortex-AI.git` | Downloads Cortex from GitHub. |
| `cd Cortex-AI` | Enters the repo. |
| `python3.11 -m pip install -e ".[server]"` | Installs the full local CLI, MCP server, UI, and self-hosted server surface. |
| `mkdir -p .cortex` | Creates the local Cortex state directory. |
| `cp docs/examples/config.toml .cortex/config.toml` | Copies the starter config for MCP and self-hosted setup. |
| `cortex scan --project .` | Audits your machine and project for existing AI context, exports, artifacts, and MCP config. |

Use `python3.11 -m pip`, not plain `pip`. Cortex requires Python 3.10+, and the source install is the most complete path.

If you only want the published package instead of the full source tree:

```bash
python3.11 -m pip install cortex-identity
```

## Portable AI

Portable AI is the "bring your context with you" layer.

It can:
- detect existing local AI exports, artifacts, instruction files, and MCP setup
- build one canonical graph from those sources
- route the right slice into each target instead of writing one giant blob everywhere
- keep that graph live over MCP for tools that support it

Typical Portable AI flow:

```bash
cortex scan --project .
cortex portable --from-detected chatgpt claude claude-code codex copilot cursor gemini grok hermes windsurf --to all --project .
cortex remember "I prefer concise, implementation-first answers." --smart
cortex sync --smart --project .
cortex mcp --config .cortex/config.toml --check
cortex mcp --config .cortex/config.toml
```

Portable AI commands:

| Command | What it does |
| --- | --- |
| `cortex scan --project .` | Detects installed tools, local exports, artifacts, direct instruction files, and MCP config without mutating your graph. |
| `cortex portable chatgpt-export.zip --to all --project .` | Ingests a raw export or existing graph and writes routed context across supported tools. |
| `cortex portable --from-detected chatgpt claude claude-code codex copilot cursor gemini grok hermes windsurf --to all --project .` | Adopts detected local context with permission, builds the canonical graph, and syncs it everywhere. |
| `cortex remember "..." --smart` | Adds one new fact or preference to the canonical graph and propagates it across supported tools. |
| `cortex sync --smart --project .` | Re-routes and re-writes the current canonical graph to local targets without re-ingesting sources. |
| `cortex status --project .` | Shows stale, missing, or incomplete local context across configured tools. |
| `cortex mcp --config .cortex/config.toml --check` | Verifies the local MCP configuration before you run it live. |
| `cortex mcp --config .cortex/config.toml` | Runs the live MCP server so tools can fetch routed context during conversations. |

Portable AI notes:
- `scan` is read-only by default.
- `portable --from-detected ...` is permissioned adoption, not silent ingestion.
- if a default Mind is configured with `cortex mind default <name>`, classic `portable`, `remember`, and `sync --smart` route through that Mind's branch-backed graph instead of the standalone canonical portability graph.
- detected local-source adoption redacts common PII by default.
- over MCP, `portability_scan` is metadata-only by default and does not expose absolute local paths or parse detected export content.

## Brainpacks

Brainpacks are local-first domain packs. Raw source files go in, and Cortex compiles them into a small wiki, a graph, claim candidates, open questions, durable artifacts, lint reports, portable bundles, and direct runtime mounts.

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

Typical Brainpack flow:

```bash
cortex pack init ai-memory --description "Portable AI memory research" --owner marc
cortex pack ingest ai-memory ~/Downloads/papers ~/notes/ai-memory --recurse
cortex pack compile ai-memory --suggest-questions
cortex pack query ai-memory "portable agent memory"
cortex pack ask ai-memory "What does this pack say about portable agent memory?" --output report
cortex pack lint ai-memory
cortex pack mount ai-memory --to hermes openclaw codex cursor claude-code --project . --smart
cortex pack export ai-memory --output ./dist/ai-memory.brainpack.zip
```

Brainpack commands:

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
| `cortex pack mount ai-memory --to hermes openclaw codex cursor claude-code --project . --smart` | Mounts the compiled pack directly into Hermes, OpenClaw, Codex, Cursor, and Claude Code. |
| `cortex pack export ai-memory --output ./dist/ai-memory.brainpack.zip` | Exports a portable Brainpack bundle archive. |
| `cortex pack import ./dist/ai-memory.brainpack.zip --store-dir ~/.cortex --as ai-memory-copy` | Imports a Brainpack bundle into another Cortex store under a chosen name. |

What `pack mount` does today:
- Hermes gets pack-derived `USER.md`, `MEMORY.md`, and managed MCP wiring.
- Codex, Cursor, and Claude Code get the routed Brainpack slice installed into their native instruction files.
- OpenClaw gets a plugin-readable Brainpack mount registry so the OpenClaw Cortex plugin injects the pack live on each turn.

## Git for AI Memory

Cortex can also treat memory like a versioned graph instead of a pile of overwritten files.

That means you can:
- commit snapshots
- branch risky experiments
- review changes before merging
- diff memory versions
- merge approved work
- trace where a claim came from
- roll back a graph when a bad change slips through

Typical Git-for-memory flow:

```bash
cortex commit portable/context.json -m "Seed canonical context"
cortex branch atlas-research --switch
cortex review --against main
cortex diff main atlas-research
cortex merge atlas-research --dry-run
cortex merge atlas-research
cortex log --branch main
```

Git-for-memory commands:

| Command | What it does |
| --- | --- |
| `cortex commit portable/context.json -m "Seed canonical context"` | Saves a graph snapshot into the local version store with a commit message. |
| `cortex branch atlas-research --switch` | Creates a new memory branch and switches to it immediately. |
| `cortex switch main` | Switches the active memory branch. |
| `cortex review --against main` | Reviews the current branch or graph against a baseline ref and applies review gates. |
| `cortex diff main atlas-research` | Shows semantic graph differences between two refs or versions. |
| `cortex merge atlas-research --dry-run` | Previews the merge result before committing it. |
| `cortex merge atlas-research` | Merges another ref into the current branch. |
| `cortex log --branch main` | Shows commit history for a branch or the global history view. |
| `cortex blame portable/context.json --label "Python"` | Traces where a specific fact or node label came from. |
| `cortex history portable/context.json --label "Python"` | Shows chronological receipts for a fact across stored versions. |
| `cortex rollback portable/context.json --to <version-id>` | Restores a prior version into a working graph and records the rollback. |

If you want the full versioned-memory surface, run:

```bash
cortex --help-all
```

## Compatibility Matrix

| Platform | Direct file / artifact support | MCP support now | Best Cortex path |
| --- | --- | --- | --- |
| Claude Desktop | No direct file target | Native | `cortex mcp` |
| Claude Code | `CLAUDE.md` | Native | `cortex mcp` + `CLAUDE.md` |
| Claude.ai | Import-ready artifacts | Partial / workspace-dependent | Artifacts first, MCP where available |
| Codex | `AGENTS.md` | Native | `cortex mcp` + `AGENTS.md` |
| Cursor | `.cursor/rules/cortex.mdc` | Native | `cortex mcp` + direct rule file |
| GitHub Copilot | `.github/copilot-instructions.md` | Native | `cortex mcp` + direct instruction file |
| Gemini CLI | `GEMINI.md` | Native | `cortex mcp` + `GEMINI.md` |
| Hermes Agent | `~/.hermes/memories/USER.md`, `~/.hermes/memories/MEMORY.md`, `~/.hermes/config.yaml` | Native | `cortex portable --to hermes` + `cortex mcp` |
| Windsurf | `.windsurfrules` | Native | `cortex mcp` + direct rule file |
| ChatGPT | Import-ready artifacts | Partial / beta / plan-dependent | Artifacts first, MCP where available |
| Grok | Import-ready artifacts | Remote MCP or app-dependent | Artifacts first, MCP where available |

`cortex mcp` is the live path for MCP-capable clients. Direct files and import-ready artifacts remain the safest universal path for everything else.

## More Docs

- Platform onboarding: [docs/PLATFORM_ONBOARDING.md](docs/PLATFORM_ONBOARDING.md)
- Portability reference: [docs/PORTABILITY.md](docs/PORTABILITY.md)
- Brainpacks reference: [docs/BRAINPACKS.md](docs/BRAINPACKS.md)
- Cortex Mind PRD: [docs/CORTEX_MIND_PRD.md](docs/CORTEX_MIND_PRD.md)
- OpenClaw quickstart: [docs/OPENCLAW_QUICKSTART.md](docs/OPENCLAW_QUICKSTART.md)
- OpenClaw native plugin: [docs/OPENCLAW_NATIVE_PLUGIN.md](docs/OPENCLAW_NATIVE_PLUGIN.md)
- Hermes quickstart: [docs/HERMES_QUICKSTART.md](docs/HERMES_QUICKSTART.md)
- Agent quickstarts: [docs/AGENT_QUICKSTARTS.md](docs/AGENT_QUICKSTARTS.md)
- Self-hosting: [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md)
- Threat model: [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)

## Uninstall

Cortex writes its managed content inside explicit `CORTEX:START` / `CORTEX:END` markers or dedicated generated files. Your own text outside those markers is left alone. To remove Cortex, delete the generated files you do not want anymore or remove the marked block from mixed files, then delete `.cortex/` and any exported `portable/` directory.
