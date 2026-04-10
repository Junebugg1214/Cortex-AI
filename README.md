[![PyPI](https://img.shields.io/pypi/v/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![Python](https://img.shields.io/pypi/pyversions/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![License](https://img.shields.io/github/license/Junebugg1214/Cortex-AI)](https://github.com/Junebugg1214/Cortex-AI/blob/main/LICENSE)

# Cortex

You use multiple AI tools.  
They all think you're a stranger.  
Cortex gives them the same Mind.

Cortex is not three unrelated products.

**Cortex is one local-first system for building, versioning, and mounting a portable Mind.**

That Mind has four layers:
- **core state**: identity, preferences, relationships, technical context, and durable memory
- **attached Brainpacks**: specialist domain cognition that can be composed in when relevant
- **version history**: review, diff, blame, merge, rollback, and governance over the graph
- **runtime mounts**: Hermes, OpenClaw, Codex, Cursor, Claude Code, ChatGPT, and other targets

The old product surfaces still matter. They just fit into one model now:
- **Portable AI** feeds and syncs a Mind's core state
- **Brainpacks** are attached specialist modules on a Mind
- **Git for AI Memory** is the version and review layer for a Mind

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

## Cortex Mind

**A Mind is the top-level object in Cortex.**

It is the thing that persists across tools, composes attached Brainpacks, and gets mounted into runtimes.

Typical Mind-first flow:

```bash
cortex mind init marc --kind person --owner marc
cortex mind default marc
cortex mind ingest marc --from-detected chatgpt claude claude-code codex cursor hermes --project .
cortex mind remember marc "I prefer concise, implementation-first responses."
cortex pack init ai-memory --description "Portable AI memory research" --owner marc
cortex pack ingest ai-memory ~/Downloads/papers ~/notes/ai-memory --recurse
cortex pack compile ai-memory --suggest-questions
cortex mind attach-pack marc ai-memory --always-on --target hermes --target codex --task-term memory
cortex mind compose marc --to chatgpt --task "memory routing"
cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"
cortex mind mounts marc
cortex mind status marc
```

Mind commands:

| Command | What it does |
| --- | --- |
| `cortex mind init marc --kind person --owner marc` | Creates a new Mind under `.cortex/minds/marc/` with manifest, core-state, branch, policy, attachment, and mount scaffolding. |
| `cortex mind default marc` | Marks one Mind as the default compatibility target so classic commands like `portable`, `remember`, and `sync --smart` can route through that Mind behind the scenes. |
| `cortex mind list` | Lists local Minds in the current Cortex store. |
| `cortex mind status marc` | Shows the Mind manifest, core-state ref, branch status, policy state, attached Brainpacks, and persisted mounts. |
| `cortex mind ingest marc --from-detected ... --project .` | Adopts detected local context directly into the Mind's core graph and commits it onto the Mind's current branch. |
| `cortex mind remember marc "..."` | Adds one new fact or preference directly to the Mind's core graph and refreshes persisted mounts from the updated state. |
| `cortex mind attach-pack marc ai-memory --always-on --target hermes --task-term memory` | Attaches an existing Brainpack to a Mind and records activation metadata for future composition. |
| `cortex mind detach-pack marc ai-memory` | Detaches a Brainpack from a Mind without deleting the Brainpack itself. |
| `cortex mind compose marc --to chatgpt --task "memory routing"` | Composes a target-aware runtime slice from the Mind's current base graph plus any attached Brainpacks that match the target and task. |
| `cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"` | Materializes the composed Mind into direct targets like Hermes, Codex, Cursor, Claude Code, and OpenClaw. |
| `cortex mind mounts marc` | Lists the persisted mount records for a Mind, including runtime-target metadata and file paths. |

## Portable AI

Portable AI is the **ingest and sync subsystem** for a Mind's core state.

Use it when you want to:
- detect existing context already on disk
- adopt that context into a Mind or canonical graph
- route different slices into different targets
- keep live runtime context available over MCP

Recommended Mind-first flow:

```bash
cortex mind default marc
cortex scan --project .
cortex mind ingest marc --from-detected chatgpt claude claude-code codex copilot cursor gemini grok hermes windsurf --project .
cortex mind remember marc "We prefer concise, implementation-first answers."
cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"
cortex mcp --config .cortex/config.toml
```

Compatibility flow:

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
| `cortex mind ingest marc --from-detected ... --project .` | Adopts detected local context directly into the selected Mind's core graph. |
| `cortex portable chatgpt-export.zip --to all --project .` | Ingests a raw export or existing graph and writes routed context across supported tools. |
| `cortex portable --from-detected ... --to all --project .` | Adopts detected local context with permission, builds the canonical graph, and syncs it everywhere. |
| `cortex mind remember marc "..."` | Adds one new fact or preference directly to a Mind's core graph. |
| `cortex remember "..." --smart` | Adds one new fact or preference through the classic portability flow. If a default Mind is configured, this routes through that Mind. |
| `cortex sync --smart --project .` | Re-routes and re-writes the current portability graph to local targets. If a default Mind is configured, this routes through that Mind. |
| `cortex status --project .` | Shows stale, missing, or incomplete local context across configured tools. |
| `cortex build --from package.json --from git-history --from github --sync --smart` | Builds portable context from project files and git history, then syncs it. |
| `cortex mcp --config .cortex/config.toml --check` | Verifies the local MCP configuration before you run it live. |
| `cortex mcp --config .cortex/config.toml` | Runs the live MCP server so tools can fetch routed context during conversations. |

Portable AI notes:
- `scan` is read-only by default.
- `portable --from-detected ...` is permissioned adoption, not silent ingestion.
- if a default Mind is configured with `cortex mind default <name>`, classic `portable`, `remember`, and `sync --smart` route through that Mind's branch-backed graph instead of a separate standalone portability graph.
- detected local-source adoption redacts common PII by default.
- over MCP, `portability_scan` is metadata-only by default and does not expose absolute local paths or parse detected export content.

## Manus Bridge

`cortex connect manus` and `cortex serve manus` turn the Manus bridge into a first-class Cortex workflow on top of the existing Mind, Brainpack, and portability tools.

Use it when you want Manus to:
- compose a Cortex Mind at runtime
- query Brainpacks as specialist cognition
- inspect portable AI context without starting from zero
- optionally write back into a Mind when you explicitly expose write tools

Recommended Manus bridge commands:

| Command | What it does |
| --- | --- |
| `cortex connect manus --check` | Checks local Manus bridge readiness, auth availability, and the recommended next steps. |
| `cortex connect manus --url https://your-https-endpoint.example/mcp --print-config` | Prints the paste-ready Manus custom MCP JSON using your configured Cortex reader key. |
| `cortex serve manus --config .cortex/config.toml --host 127.0.0.1 --port 8790` | Runs the hosted Manus bridge locally at `/mcp`. Put it behind HTTPS before connecting it to Manus. |
| `cortex serve manus --config .cortex/config.toml --check` | Prints bridge diagnostics, exposed tools, and the Manus MCP path before you deploy it. |
| `cortex serve manus --config .cortex/config.toml --allow-write-tools --tool mind_mount` | Adds the curated Manus write-tool set and any extra explicitly named tools such as `mind_mount`. |

The legacy `cortex-manus` entrypoint still works and maps to the same bridge runtime.

If `cortex-manus` is missing after a local source install, reinstall with `python3.11 -m pip install --user --no-build-isolation -e ".[server]"` and add `~/Library/Python/3.11/bin` to `PATH` on macOS if needed. See [docs/MANUS_QUICKSTART.md](docs/MANUS_QUICKSTART.md) for the full troubleshooting steps.

## Brainpacks

Brainpacks are the **specialist cognition subsystem** for a Mind.

They are not a second top-level identity object. They are attachable domain modules that Cortex can compile, query, lint, bundle, and mount on their own or compose into a Mind.

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
cortex mind attach-pack marc ai-memory --always-on --target hermes --target codex --task-term memory
cortex mind compose marc --to hermes --task "memory support"
cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"
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
| `cortex pack mount ai-memory --to hermes openclaw codex cursor claude-code --project . --smart` | Mounts the compiled Brainpack directly into supported runtimes and tools. |
| `cortex pack export ai-memory --output ./dist/ai-memory.brainpack.zip` | Exports a portable Brainpack bundle archive. |
| `cortex pack import ./dist/ai-memory.brainpack.zip --store-dir ~/.cortex --as ai-memory-copy` | Imports a Brainpack bundle into another Cortex store under a chosen name. |
| `cortex mind attach-pack marc ai-memory ...` | Attaches the Brainpack to a Mind so it can be composed selectively or always-on at runtime. |
| `cortex mind compose marc --to hermes --task "memory support"` | Shows what the Mind plus attached Brainpacks will actually look like for a given runtime and task. |

What `pack mount` does today:
- Hermes gets pack-derived `USER.md`, `MEMORY.md`, and managed MCP wiring.
- Codex, Cursor, and Claude Code get the routed Brainpack slice installed into their native instruction files.
- OpenClaw gets a plugin-readable Brainpack mount registry so the OpenClaw Cortex plugin injects the pack live on each turn.

## Git for AI Memory

Git for AI Memory is the **version history and governance subsystem** for a Mind.

Today the low-level graph commands still operate directly on refs and branches, but the Mind model is what gives those refs a durable identity, mounted targets, and attached specialist cognition.

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
| Hermes Agent | `~/.hermes/memories/USER.md`, `~/.hermes/memories/MEMORY.md`, `~/.hermes/config.yaml` | Native | `cortex mind mount` or `cortex portable --to hermes` + `cortex mcp` |
| Windsurf | `.windsurfrules` | Native | `cortex mcp` + direct rule file |
| ChatGPT | Import-ready artifacts | Partial / beta / plan-dependent | Artifacts first, MCP where available |
| Grok | Import-ready artifacts | Remote MCP or app-dependent | Artifacts first, MCP where available |

`cortex mcp` is the live path for MCP-capable clients. Direct files and import-ready artifacts remain the safest universal path for everything else.

## More Docs

- Mind guide: [docs/MINDS.md](docs/MINDS.md)
- Platform onboarding: [docs/PLATFORM_ONBOARDING.md](docs/PLATFORM_ONBOARDING.md)
- Portable AI subsystem: [docs/PORTABILITY.md](docs/PORTABILITY.md)
- Brainpacks subsystem: [docs/BRAINPACKS.md](docs/BRAINPACKS.md)
- Cortex Mind PRD: [docs/CORTEX_MIND_PRD.md](docs/CORTEX_MIND_PRD.md)
- CLI Unification PRD: [docs/CLI_UNIFICATION_PRD.md](docs/CLI_UNIFICATION_PRD.md)
- Manus quickstart: [docs/MANUS_QUICKSTART.md](docs/MANUS_QUICKSTART.md)
- OpenClaw quickstart: [docs/OPENCLAW_QUICKSTART.md](docs/OPENCLAW_QUICKSTART.md)
- OpenClaw native plugin: [docs/OPENCLAW_NATIVE_PLUGIN.md](docs/OPENCLAW_NATIVE_PLUGIN.md)
- Hermes quickstart: [docs/HERMES_QUICKSTART.md](docs/HERMES_QUICKSTART.md)
- Agent quickstarts: [docs/AGENT_QUICKSTARTS.md](docs/AGENT_QUICKSTARTS.md)
- Self-hosting: [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md)
- Threat model: [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)

## Uninstall

Cortex writes its managed content inside explicit `CORTEX:START` / `CORTEX:END` markers or dedicated generated files. Your own text outside those markers is left alone. To remove Cortex, delete the generated files you do not want anymore or remove the marked block from mixed files, then delete `.cortex/` and any exported `portable/` directory.
