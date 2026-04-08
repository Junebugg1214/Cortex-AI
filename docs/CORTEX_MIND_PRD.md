# Cortex Mind PRD

## Summary

`cortex mind` is the missing top-level abstraction that unifies Cortex's three existing product surfaces:

- Portable AI
- Brainpacks
- Git for AI Memory

Today Cortex is powerful, but it still reads as several adjacent systems:
- a portable context layer
- a Brainpack domain-pack layer
- a versioned graph/memory layer

`cortex mind` turns those into one product:

**a portable, versioned, composable mind that can carry continuity across tools and mount specialist Brainpacks at runtime.**

This PRD is the lockfile for that architecture. Implementation should follow this model instead of introducing a second parallel abstraction.

## Product Thesis

Users do not actually want:
- sync files
- pack queries
- graph branches

They want:

**the same agent mind to exist across platforms, evolve safely, and load the right specialist state at the right time.**

That means Cortex should become:

**the system for composing, versioning, and mounting portable minds.**

## Goals

- define a single top-level object for Cortex: the Mind
- unify Portable AI, Brainpacks, and Git-for-memory under that object
- make runtime composition explicit, first-class, and target-aware
- keep the system local-first and compatible with existing Cortex data
- enable implementation in thin, safe slices instead of a large rewrite

## Non-Goals

- replacing Brainpacks as a concept
- replacing the existing graph store
- rewriting all existing commands immediately
- building collaborative/cloud mind-sharing in v1
- building an autonomous planning/orchestration system in v1

## Core Product Model

A **Mind** is the only top-level object in Cortex.

Everything else becomes a property or operation on a Mind:

- Portable AI feeds the Mind's core state
- Brainpacks attach to the Mind
- Git-for-memory versions the Mind
- mounts and MCP render the Mind into runtimes
- composition builds the exact state a runtime should receive

The unifying rule is:

**there is one top-level object, and all existing Cortex capabilities operate on it.**

## Mental Model

```text
Mind
├── core state
├── attached Brainpacks
├── branches and history
├── policies
├── mounts
└── compositions
```

Composition is the key engine:

```text
composed mind state =
core state
+ active branch changes
+ attached Brainpacks selected for the task
+ target disclosure policy
+ target routing rules
```

Without composition, `mind` is branding.
With composition, `mind` becomes architecture.

## User Value

`cortex mind` should let a user say:

- this is my persistent base mind
- these Brainpacks are attached to it
- this branch is the working state for a launch, project, or experiment
- render the right version of this mind for Hermes, OpenClaw, Codex, Cursor, or Claude Code

The user should no longer need to reason about:
- separate portable graphs
- separate pack state
- separate branch workflows

They should reason about:

**one mind, many runtime compositions**

## Exact Data Model

### 1. Mind Manifest

Each Mind has a canonical manifest:

```json
{
  "id": "marc",
  "label": "Marc",
  "kind": "person",
  "owner": "marc",
  "created_at": "2026-04-07T00:00:00Z",
  "updated_at": "2026-04-07T00:00:00Z",
  "default_branch": "main",
  "current_branch": "main",
  "default_policy": "professional"
}
```

Required fields:
- `id`: stable mind id
- `label`: display label
- `kind`: `person`, `agent`, `project`, or `team`
- `owner`: human or system owner label
- `default_branch`: default memory branch
- `current_branch`: active working branch
- `default_policy`: default disclosure policy

### 2. Core State

The Mind's durable base state:

```json
{
  "graph_ref": "refs/minds/marc/branches/main",
  "categories": [
    "identity",
    "professional_context",
    "business_context",
    "active_priorities",
    "technical_expertise",
    "relationships",
    "constraints",
    "values",
    "user_preferences",
    "communication_preferences"
  ]
}
```

This is where the current Portable AI pipeline lands:
- `scan`
- `portable`
- `remember`
- `sync`

### 3. Attachments

Brainpacks are attached modules on a Mind, not a separate top-level system:

```json
{
  "brainpacks": [
    {
      "id": "ai-memory",
      "pack_ref": "packs/ai-memory",
      "mode": "attached",
      "scope": "specialist",
      "priority": 100,
      "activation": {
        "targets": ["hermes", "openclaw", "claude-code"],
        "task_terms": ["memory", "brain state", "context", "agent"],
        "always_on": false
      }
    }
  ]
}
```

Attachment fields:
- `id`: stable attachment id
- `pack_ref`: Brainpack reference
- `mode`: initially `attached`
- `scope`: `specialist` in v1
- `priority`: composition priority
- `activation.targets`: optional target filter
- `activation.task_terms`: optional task-term activators
- `activation.always_on`: whether the pack is always included

### 4. Branches

Branches version the Mind:

```json
{
  "branches": {
    "main": {
      "head": "v_01JABC",
      "created_at": "2026-04-07T00:00:00Z"
    },
    "launch-week": {
      "head": "v_01JABD",
      "created_at": "2026-04-08T00:00:00Z",
      "from": "main"
    }
  }
}
```

This is where Git-for-memory lives once unified.

### 5. Policies

Policies control how the Mind is disclosed and governed:

```json
{
  "default_disclosure": "professional",
  "target_overrides": {
    "copilot": "technical",
    "chatgpt": "professional"
  },
  "approval_rules": {
    "merge_to_main_requires_review": true,
    "external_mount_requires_explicit_approval": true
  }
}
```

### 6. Mounts

Mounts record where the Mind is materialized:

```json
{
  "mounts": [
    {
      "target": "hermes",
      "enabled": true,
      "branch": "main",
      "policy": "professional",
      "smart": true,
      "max_chars": 1500,
      "last_materialized_at": "2026-04-07T01:00:00Z"
    }
  ]
}
```

### 7. Compositions

Compositions are runtime builds of a Mind for a specific task and target:

```json
{
  "request": {
    "mind_id": "marc",
    "branch": "launch-week",
    "target": "openclaw",
    "task": "answer investor questions about Cortex",
    "channel": "whatsapp"
  },
  "result": {
    "base_graph_ref": "v_01JABD",
    "included_brainpacks": ["fundraising", "ai-memory"],
    "applied_policy": "professional",
    "selected_tags": [
      "identity",
      "professional_context",
      "business_context",
      "active_priorities",
      "constraints"
    ],
    "rendered_as": "openclaw_prompt_context"
  }
}
```

This is the most important new object after the Mind itself.

## Storage Layout

Proposed local layout:

```text
.cortex/
  minds/
    marc/
      manifest.json
      attachments.json
      mounts.json
      policies.json
      compositions/
      refs/
  packs/
    ai-memory/
  versions/
  indexes/
```

Notes:
- existing `.cortex/packs/` remains valid
- existing version store remains valid
- the Mind should reference existing primitives, not duplicate them

## CLI Surface

### V1 commands

```bash
cortex mind init marc --kind person
cortex mind list
cortex mind status marc
cortex mind attach-pack marc ai-memory
cortex mind detach-pack marc ai-memory
cortex mind mounts marc
cortex mind compose marc --to hermes --task "coding support"
```

### V2 commands

```bash
cortex mind ingest marc --from-detected chatgpt claude claude-code codex cursor
cortex mind remember marc "I prefer concise, implementation-first responses."
cortex mind branch marc launch-week
cortex mind switch marc launch-week
cortex mind merge marc launch-week
cortex mind mount marc --to hermes openclaw codex cursor claude-code --smart
```

### CLI design rules

- `cortex mind` becomes a new top-level group
- v1 is additive, not a replacement
- existing commands continue to work
- existing commands should later become thin wrappers around mind-aware flows where appropriate

## MCP Surface

The Mind should eventually expose:

- `mind_list`
- `mind_status`
- `mind_context`
- `mind_compose`
- `mind_mount_status`

`mind_compose` is the critical MCP tool.

Example:

```json
{
  "mind": "marc",
  "target": "openclaw",
  "task": "answer investor questions about Cortex",
  "branch": "launch-week"
}
```

Output should include:
- selected branch
- included Brainpacks
- selected tags
- policy applied
- rendered context body

## How This Unifies Existing Cortex

### Portable AI

Portable AI becomes:

**the ingest and sync layer for a Mind's core state**

That means:
- detected-source adoption feeds a Mind
- `remember` mutates a Mind
- `sync` materializes a Mind

### Brainpacks

Brainpacks become:

**attachable specialist cognition on a Mind**

That means:
- they are no longer a parallel top-level story
- they are modular extensions of a Mind

### Git for AI Memory

Git-for-memory becomes:

**the version history of a Mind**

That means:
- branch a Mind
- review a Mind
- merge a Mind
- diff a Mind
- roll back a Mind

## Migration Strategy

No destructive migration in v1.

### Phase 1
- create Mind manifests and storage
- allow attaching existing Brainpacks
- allow composing from existing graphs and packs

### Phase 2
- alias current portable graph flows into a default Mind
- support `mind remember`, `mind ingest`, and `mind mount`

### Phase 3
- let existing commands operate through a default Mind behind the scenes

Important rule:

**existing `portable`, `pack`, and versioned-memory flows must continue to work during the transition.**

## V1 Scope

Ship first:
- `mind init`
- `mind list`
- `mind status`
- `mind attach-pack`
- `mind detach-pack`
- `mind compose`
- `mind mounts`
- minimal storage layout
- composition engine over existing graph + Brainpack primitives

Do not ship in v1:
- automatic migration of every existing command
- cloud sync or collaboration
- autonomous pack-selection agents
- team/shared minds

## Immediate Implementation PR Sequence

### PR 1: Mind Foundation
- add `cortex/minds.py`
- add `cortex mind init|list|status`
- add storage layout under `.cortex/minds/`
- add tests for manifest lifecycle

### PR 2: Mind Attachments
- add `mind attach-pack` and `mind detach-pack`
- attach existing Brainpacks to Minds
- add status/mount metadata

### PR 3: Mind Compose
- build composition engine
- implement target-aware composed output from:
  - core graph
  - active branch
  - attached Brainpacks
  - target policy
- add CLI and service support

### PR 4: Mind Mount
- mount a composed Mind into Hermes, OpenClaw, Codex, Cursor, and Claude Code
- reuse existing portability installers and runtime hooks

### PR 5: Mind-Aware Portable Flows
- `mind ingest`
- `mind remember`
- optional default-mind alias for existing portable commands

## Risks

- introducing a second abstraction without actually consolidating behavior
- duplicating state between Mind core graphs and existing portability graphs
- overbuilding composition before the Mind foundation exists
- confusing users if both old and new commands feel equally primary

## Success Criteria

`cortex mind` succeeds if:

- users can explain Cortex around one top-level object instead of three separate subsystems
- a Mind can attach Brainpacks and compose target-aware runtime state
- the same Mind can be mounted into multiple runtimes cleanly
- existing Portable AI and Brainpack features feel more coherent after the change, not less

## Product Positioning

The clean positioning after this ships:

**Cortex is a brain-state operating system for agents.**

Portable AI was the wedge.  
Portable minds are the category.
