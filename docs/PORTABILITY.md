# Portable AI

Portable AI is the **ingest and sync subsystem** for a Cortex Mind.

It is how a Mind learns what already exists on disk, stages that context for review, and materializes the right slice into each runtime or tool.

If you already use the older portability commands directly, that still works. The important change is the model:

- without a default Mind, classic portability commands still operate on the standalone portability graph
- with a default Mind, those same commands route through that Mind's branch-backed core graph

## Start Here

Recommended Mind-first flow:

```bash
cortex mind init marc --kind person --owner marc
cortex mind default marc
cortex scan --project .
cortex mind ingest marc --from-detected chatgpt claude claude-code codex copilot cursor gemini grok hermes windsurf --project .
cortex mind remember marc "We use Vitest now."
cortex mind mount marc --to hermes codex cursor claude-code openclaw --task "support"
```

Compatibility flow:

```bash
cortex portable chatgpt-export.zip --to all --project .
cortex scan --project .
cortex remember "We use Vitest now." --smart
cortex sync --smart
```

If you want copy-paste first-run flows by platform, see [PLATFORM_ONBOARDING.md](PLATFORM_ONBOARDING.md).

## What Portable AI Does

Portable AI is responsible for four things:

1. **detect** local AI exports, artifacts, instruction files, and MCP setup
2. **stage or adopt** that context into a Mind or canonical portability graph
3. **route** the right slice into each target instead of writing one giant blob everywhere
4. **serve** live context over MCP for runtimes that can fetch it during conversations

## Commands

### `cortex scan`

Audits the current machine and portability state to show what each supported tool knows, how many facts it has, and whether that context is stale or missing.

It also auto-detects known local instruction files, artifacts, and MCP config definitions from the compatibility matrix, so already-installed tools can show up even before Cortex has synced them. By default it searches the current project plus `~/Downloads`, `~/Desktop`, and `~/Documents` recursively for known export and artifact names, and it prefers the newest match when multiple candidates exist.

Detection is permissioned. `scan` does not mutate the graph.

### `cortex mind ingest`

Queues detected local platform sources as an unverified review proposal for a Mind:

```bash
cortex mind ingest marc --from-detected chatgpt claude claude-code codex cursor hermes --project .
```

This is the recommended path when you are already working Mind-first and want a reviewable quarantine step before canonical Mind state changes.

### `cortex portable`

Loads an existing Cortex graph or extracts one from a raw export, then writes or generates target-specific context for the tools you selected.

Examples:

```bash
cortex portable chatgpt-export.zip --to all --project .
cortex portable context.json --to codex cursor claude-code hermes --project .
cortex portable --from-detected chatgpt claude claude-code codex copilot cursor gemini grok hermes windsurf --to all --project .
```

### `cortex mind remember`

Updates a Mind's core state directly:

```bash
cortex mind remember marc "We migrated from PostgreSQL to CockroachDB in January."
```

### `cortex remember`

Updates the classic portability graph once, then propagates that new fact across supported portability targets.

If a default Mind is configured with `cortex mind default <name>`, this command routes through that Mind behind the scenes.

### `cortex sync --smart`

Routes different slices of context to different tools instead of copying the same blob everywhere.

If a default Mind is configured, `sync --smart` re-materializes that Mind's current branch-backed core state into the relevant targets.

Typical routing shape:

- coding assistants get technical stack, active project, and conventions
- broader chat tools get more personal and professional context
- each tool gets a tighter, more useful context window

Current smart-routing defaults:

| Tool | Routed categories |
| --- | --- |
| `claude-code`, `codex` | `technical_expertise`, `domain_knowledge`, `active_priorities`, `communication_preferences`, `user_preferences` |
| `cursor`, `windsurf` | `technical_expertise`, `active_priorities`, `communication_preferences`, `user_preferences`, `domain_knowledge` |
| `copilot` | `technical_expertise`, `communication_preferences`, `user_preferences`, `constraints` |
| `chatgpt`, `grok` | `identity`, `professional_context`, `business_context`, `active_priorities`, `domain_knowledge`, `values` |
| `hermes` | `identity`, `professional_context`, `business_context`, `active_priorities`, `technical_expertise`, `domain_knowledge`, `relationships`, `constraints`, `communication_preferences`, `user_preferences`, `values` |
| `gemini` | `domain_knowledge`, `professional_context`, `business_context`, `active_priorities`, `technical_expertise` |

### `cortex status`

Shows which configured tools are stale or missing facts compared to the current routed state.

### `cortex build`

Bootstraps portable context from things that already exist:

- `package.json`
- `pyproject.toml`
- `Cargo.toml`
- local GitHub-style repositories
- git history
- resumes and profile docs

### `cortex audit`

Compares what different tools believe and flags divergence or drift so you can catch outdated AI context before it causes bad advice.

### `cortex switch`

Wraps import, filtering, and target-specific generation into one platform-switch flow.

Example:

```bash
cortex switch --from chatgpt-export.zip --to claude
```

## Target Model

Cortex is explicit about how each target works.

- **direct installs** write into local instruction files the tool already understands
- **import-ready artifacts** generate files you can paste or import into chat apps that do not expose a stable local file path
- **Mind mounts** materialize the composed Mind into a supported runtime or tool

## Supported Targets

| Target | Delivery | Output |
| --- | --- | --- |
| `claude-code` | Direct install | `~/.claude/CLAUDE.md` and `./CLAUDE.md` |
| `codex` | Direct install | `./AGENTS.md` |
| `cursor` | Direct install | `./.cursor/rules/cortex.mdc` |
| `copilot` | Direct install | `./.github/copilot-instructions.md` |
| `gemini` | Direct install | `./GEMINI.md` |
| `hermes` | Direct install | `~/.hermes/memories/USER.md`, `~/.hermes/memories/MEMORY.md`, `~/.hermes/config.yaml` |
| `windsurf` | Direct install | `./.windsurfrules` |
| `claude` | Import-ready artifacts | `portable/claude/claude_preferences.txt`, `portable/claude/claude_memories.json` |
| `chatgpt` | Import-ready artifacts | `portable/chatgpt/custom_instructions.md`, `portable/chatgpt/custom_instructions.json` |
| `grok` | Import-ready artifacts | `portable/grok/context_prompt.md`, `portable/grok/context_prompt.json` |

For a sample generated Claude Code file, see [`docs/examples/CLAUDE.generated.md`](examples/CLAUDE.generated.md).
That example is separate from the repository root [`CLAUDE.md`](../CLAUDE.md), which is a repository guide for working on Cortex itself.

## Notes

- `scan` is read-only by default.
- `portable --from-detected ...` is explicit adoption, not silent ingestion.
- detected local-source adoption redacts common PII by default.
- direct instruction files import only the managed Cortex block by default unless you opt into `--include-unmanaged-text`.
- over MCP, `portability_scan` is metadata-only by default and does not expose absolute local paths or parse detected export content.
- the portability layer keeps storage user-owned. It does not upload memory anywhere.
- lower-level commands like `extract`, `import`, `context-write`, and adapter `sync` still exist if you want finer control.
