# Portability

Portability is the product front door in Cortex.

The promise is simple:

**One command. All your AI context. Every tool.**

## Start Here

```bash
cortex portable chatgpt-export.zip --to all --project .
```

If you want copy-paste first-run flows by platform, see [PLATFORM_ONBOARDING.md](PLATFORM_ONBOARDING.md).

That one command:

1. loads an existing Cortex graph or extracts one from a raw export
2. saves a portable graph-shaped `context.json` in the current v5-style format
3. writes or generates target-specific context for the tools you selected

## Portability Control Plane

Once you have a canonical portable context graph, these commands become the day-to-day workflow:

```bash
# audit what each tool knows
cortex scan

# teach once and propagate
cortex remember "We use Vitest now"

# route the right slice to each tool
cortex sync --smart

# show stale or missing context
cortex status

# build context from repos, manifests, and git history
cortex build --from package.json --from git-history --from github --sync --smart

# detect cross-tool drift or contradictions
cortex audit

# switch platforms with target-aware output
cortex switch --from chatgpt-export.zip --to claude
```

## Target Model

Cortex is explicit about how each target works.

- **Direct installs** write into local instruction files the tool already understands.
- **Import-ready artifacts** generate files you can paste or import into chat apps that do not expose a stable local file path.

## Supported Targets

| Target | Delivery | Output |
|---|---|---|
| `claude-code` | Direct install | `~/.claude/CLAUDE.md` and `./CLAUDE.md` |
| `codex` | Direct install | `./AGENTS.md` |
| `cursor` | Direct install | `./.cursor/rules/cortex.mdc` |
| `copilot` | Direct install | `./.github/copilot-instructions.md` |
| `gemini` | Direct install | `./GEMINI.md` |
| `windsurf` | Direct install | `./.windsurfrules` |
| `claude` | Import-ready artifacts | `portable/claude/claude_preferences.txt`, `portable/claude/claude_memories.json` |
| `chatgpt` | Import-ready artifacts | `portable/chatgpt/custom_instructions.md`, `portable/chatgpt/custom_instructions.json` |
| `grok` | Import-ready artifacts | `portable/grok/context_prompt.md`, `portable/grok/context_prompt.json` |

For a sample generated Claude Code file, see [`docs/examples/CLAUDE.generated.md`](examples/CLAUDE.generated.md).
That example is separate from the repository root [`CLAUDE.md`](../CLAUDE.md), which is a contributor guide for working on Cortex itself.

## What The New Commands Do

### `cortex scan`

Audits the current machine and portability state to show what each supported tool knows, how many facts it has, and whether that context is stale or missing.

### `cortex remember`

Updates the canonical portable context graph once, then propagates that new fact across all supported portability targets by default.

Example:

```bash
cortex remember "We migrated from PostgreSQL to CockroachDB in January"
```

### `cortex sync --smart`

Routes different slices of context to different tools instead of copying the same blob everywhere.

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
| `gemini` | `domain_knowledge`, `professional_context`, `business_context`, `active_priorities`, `technical_expertise` |

### `cortex status`

Shows which configured tools are stale or missing facts compared to the canonical context graph.

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

## Examples

Import a ChatGPT export and install everywhere:

```bash
cortex portable chatgpt-export.zip --to all --project .
```

Start from an existing graph and only target coding tools:

```bash
cortex portable context.json --to claude-code codex cursor copilot gemini windsurf --project .
```

Generate only ChatGPT and Grok artifacts:

```bash
cortex portable context.json --to chatgpt grok -o ./portable
```

Dry run without writing files:

```bash
cortex portable chatgpt-export.zip --to all --project . --dry-run
```

Build from existing project files and immediately sync smart slices:

```bash
cortex build --from package.json --from git-history --from github --sync --smart
```

For a fuller onboarding guide with per-platform import and sync commands, see [PLATFORM_ONBOARDING.md](PLATFORM_ONBOARDING.md).

## Notes

- `claude-code` installs both a global user file and a project file.
- `gemini-cli` is still accepted as an alias for `gemini`.
- `remember` now updates all supported portability targets by default, including import-ready artifacts for chat tools.
- The portability layer keeps storage user-owned. It does not upload memory anywhere.
- Lower-level commands like `extract`, `import`, `context-write`, and adapter `sync` still exist if you want finer control.
