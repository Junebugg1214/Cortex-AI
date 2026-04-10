# Cortex CLI Unification PRD

## Overview

Cortex has outgrown its original CLI shape.

The product now has a strong core idea:

**Cortex gives AI tools the same portable Mind.**

But the CLI still exposes too much of Cortex's internal history:

- legacy graph/versioning commands
- portability-first commands
- Mind-first commands
- Brainpack commands
- runtime/server commands

That makes Cortex feel more like a toolkit than a first-class product.

This PRD defines a unified, production-ready CLI that is:

- Mind-first
- task-shaped
- safe by default
- easy to learn
- still powerful for expert users

## Problem

Today the CLI has three major UX issues.

### 1. The top-level surface is too large

`cortex --help-all` exposes a long list of commands that mixes:

- old low-level graph operations
- portability workflows
- Mind and Brainpack workflows
- operational/server commands

The result is powerful, but not approachable.

### 2. The happy path is not obvious

A new user should be able to answer:

- How do I start?
- How do I create my Mind?
- How do I connect Cortex to Manus or Codex?
- How do I know if my setup is healthy?

Right now those answers are spread across several command families and docs.

### 3. Store and config behavior is too easy to misconfigure

Cortex is local-first, which is a strength, but the CLI still makes it too easy to:

- write to the wrong store
- create accidental second stores
- confuse repo root state with `.cortex` state
- get correct results locally but incorrect results in a bridge or runtime

That is not production-grade CLI behavior.

## Product Goal

Make Cortex feel like:

1. one product
2. one obvious command path
3. one safe local store model
4. one clear set of runtime connection flows

The CLI should help users succeed without requiring them to understand Cortex internals first.

## Non-Goals

This effort does not:

- remove advanced graph/versioning features
- eliminate backward compatibility in one release
- replace the web UI
- redesign the full storage engine
- ship collaborative/cloud Cortex in v1

## Design Principles

### Mind-first

The Mind is the top-level object in Cortex.

That means the primary user flows should feel like:

- initialize a Cortex workspace
- create or adopt a Mind
- teach the Mind something
- attach Brainpacks to the Mind
- connect the Mind to external runtimes

### Intent over architecture

Commands should match user goals, not internal modules.

Users think in terms of:

- set up Cortex
- connect Manus
- remember something
- attach a Brainpack
- compose a context slice

They do not think in terms of:

- graph refs
- canonical portability graph
- instruction-file adapters
- MCP bridge transport details

### Progressive disclosure

Normal users should see a small, coherent surface.

Power users should still have access to low-level graph, review, blame, merge, and governance commands, but those should not dominate default help.

### Safe defaults

The CLI should strongly prefer:

- one authoritative store
- one default Mind
- scoped keys
- explicit runtime connections
- explicit write behavior

### Scriptable and automatable

Production-ready CLI behavior requires:

- stable `--json`
- clean exit codes
- `--check`
- `--dry-run`
- `--yes`
- idempotent `init` and `connect`

## Proposed Top-Level CLI

The default top-level surface should be:

- `cortex init`
- `cortex mind ...`
- `cortex pack ...`
- `cortex connect ...`
- `cortex sync`
- `cortex status`
- `cortex doctor`
- `cortex serve ...`
- `cortex ui`

Everything else should move behind advanced surfaces:

- `cortex admin ...`
- `cortex graph ...`
- `cortex --help-all`

## Command Model

### `cortex init`

This becomes the first-class onboarding command.

Responsibilities:

- discover or create the authoritative store
- create `.cortex/config.toml` when missing
- create reader/writer tokens if needed
- create a default Mind or adopt an existing one
- optionally scan for detected AI context
- print the next recommended commands

Requirements:

- idempotent
- safe to re-run
- explicit about the resolved store path
- TTY-friendly onboarding, non-interactive safe defaults for automation

### `cortex mind`

Primary object management.

Supported subcommands:

- `init`
- `list`
- `status`
- `default`
- `ingest`
- `remember`
- `attach-pack`
- `detach-pack`
- `compose`
- `mount`
- `mounts`

This is the primary day-to-day Cortex surface.

### `cortex pack`

Specialist cognition management.

Supported subcommands:

- `init`
- `list`
- `ingest`
- `compile`
- `status`
- `query`
- `ask`
- `lint`
- `mount`
- `export`
- `import`

Brainpacks remain first-class, but conceptually they are modules attached to Minds.

### `cortex connect`

This is a new first-class runtime connection surface.

Supported subcommands:

- `manus`
- `hermes`
- `codex`
- `cursor`
- `claude-code`
- `openclaw`

Each target should support:

- `--check`
- `--print-config`
- `--install`
- `--test`

Responsibilities:

- verify store resolution
- verify auth
- verify required files or MCP endpoints
- print or install runtime-specific config
- test that the connection really works

The goal is to replace fragile manual setup with productized flows.

### `cortex serve`

This groups runtime/server processes.

Supported subcommands:

- `api`
- `mcp`
- `manus`
- `ui`

This is clearer than mixing `server`, `mcp`, `ui`, and a separate `cortex-manus` entrypoint in the primary mental model.

Standalone entrypoints can still exist for convenience.

### `cortex admin`

Advanced operational and governance surfaces.

Candidates:

- governance
- remote
- backup
- benchmark
- release-notes
- openapi

### `cortex graph`

Advanced graph/versioning surfaces.

Candidates:

- query
- diff
- blame
- history
- claim
- contradictions
- drift
- timeline
- viz
- commit
- branch
- switch
- merge
- review
- rollback
- log

These remain important, but they should not dominate the default Cortex experience.

## Store Resolution Contract

This is the most important production hardening change.

The CLI must resolve one authoritative store in a deterministic way.

Resolution order:

1. explicit `--store-dir`
2. `CORTEX_STORE_DIR`
3. nearest `.cortex/config.toml` walking upward from `cwd`
4. nearest `.cortex/` walking upward from `cwd`
5. fallback `~/.cortex`

Production requirements:

- commands should print the resolved store path unless `--quiet`
- `doctor` should detect accidental second stores
- `doctor --fix` should offer or apply repair
- `store_dir = "."` should be discouraged and clearly flagged
- runtime connectors should surface the resolved store path in diagnostics

## Backward Compatibility

Legacy commands remain supported for at least two releases, but the default help should point users toward the unified model.

Examples:

- `portable` becomes a compatibility alias for Mind-aware ingest/sync
- `remember` becomes a compatibility alias for default-Mind remember
- `server`, `mcp`, and `ui` remain, but `serve` becomes the recommended product surface

Legacy commands should print migration guidance in normal human-readable mode.

## Output Contract

Every first-class command should follow a consistent output contract:

- short summary
- resolved store path when relevant
- resolved Mind or target when relevant
- warnings and fix suggestions when relevant
- next-step guidance

For machine use:

- stable `--json`
- no human chatter in JSON mode
- consistent keys for `status`, `warnings`, `next_steps`, and `resolved_store`

## UX Standards

### First-run UX

The first-run path should be:

```bash
cortex init
```

Then Cortex should tell the user exactly what to do next.

Example:

```text
Initialized Cortex at /Users/marcsaint-jour/Desktop/Cortex-AI/.cortex
Default Mind: marc

Next:
  cortex mind remember marc "I prefer concise technical answers."
  cortex connect manus --print-config
  cortex status
```

### Error UX

Errors should be specific and actionable.

Bad:

```text
Error: Mind does not exist.
```

Better:

```text
Error: Mind 'marc' does not exist in /Users/.../.cortex.
Try:
  cortex mind list --store-dir /Users/.../.cortex
  cortex mind init marc --store-dir /Users/.../.cortex
```

### Runtime connection UX

`connect` should feel turnkey.

For example:

```bash
cortex connect manus --print-config
```

should print:

- the exact HTTPS endpoint shape
- required headers
- the current resolved store
- which tools will be exposed
- the next test command

## Production Readiness Requirements

The unified CLI is production-ready when it satisfies all of the following:

- deterministic store resolution
- no silent second-store creation in common flows
- idempotent `init`
- stable `connect` diagnostics
- `serve` health checks
- consistent `--json` schemas
- explicit warnings for unsafe config
- clear upgrade path for legacy command users

## End-to-End Smoke Test Plan

The unified CLI must have explicit smoke coverage for the main user journeys.

### 1. New user setup

Flow:

- `cortex init`
- `cortex mind status`
- `cortex status`

Must verify:

- store creation
- config creation
- token creation
- default Mind creation
- stable output and exit codes

### 2. Mind-first local use

Flow:

- `cortex mind remember`
- `cortex mind status`
- `cortex mind compose`

Must verify:

- writes land in the correct store
- default Mind resolution works
- next-step guidance is present

### 3. Brainpack flow

Flow:

- `cortex pack init`
- `cortex pack ingest`
- `cortex pack compile`
- `cortex mind attach-pack`
- `cortex mind compose`

Must verify:

- pack and Mind integration works
- attachment state appears in status
- compose includes pack-derived content

### 4. Manus connection flow

Flow:

- `cortex connect manus --print-config`
- `cortex serve manus`
- external initialize + `mind_list`

Must verify:

- correct store resolution
- correct auth guidance
- correct pinned MCP protocol
- stateless Manus tool access still works

### 5. Store mismatch detection

Flow:

- create ambiguous store situation
- run `cortex doctor`
- run `cortex doctor --fix`

Must verify:

- mismatch is detected
- fix guidance is actionable
- repaired setup is clean

## Success Metrics

The CLI unification effort succeeds if:

- new users can complete first setup without docs
- support incidents around store confusion drop materially
- runtime connection setup time decreases
- default help is visibly shorter and easier to scan
- advanced users still retain full graph/versioning power via `admin`, `graph`, or `--help-all`

## Implementation Sequence

### PR 1: CLI Foundation Unification

- add `cortex init`
- add canonical store discovery groundwork
- simplify top-level help around first-class commands
- add warning rails for ambiguous store setups

### PR 2: `cortex connect`

- add `connect manus`
- add target-specific config printing and validation
- start connecting Hermes/Codex/Cursor/Claude Code under the same model

### PR 3: `cortex serve`

- unify `server`, `mcp`, `ui`, and Manus bridge runtime guidance
- add health-check-oriented UX

### PR 4: `doctor --fix`

- detect and repair store/config mismatches
- flag `store_dir = "."`
- help users recover from accidental second stores

### PR 5: Help and compatibility cleanup

- shorten default help
- demote advanced surfaces
- add alias guidance for legacy commands

### PR 6: Smoke hardening

- add end-to-end smoke tests for all first-class flows
- lock JSON contracts
- verify backward-compatible flows still work

## Recommendation

The next implementation PR should be:

**CLI Foundation Unification**

That means:

- `cortex init`
- store discovery hardening
- clearer default help
- groundwork for `connect`

This is the highest-leverage step toward making Cortex feel first-class, production-ready, and genuinely unified.
