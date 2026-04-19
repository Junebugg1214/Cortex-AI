# Cortex Threat Model

This is the concise threat model for the self-hosted, user-owned Cortex beta.

Deployment assumption:

- default mode is `local-single-user`
- hosted use means operator-managed `hosted-service`, not a shared Cortex cloud

## Scope

In scope:

- `cortexd` REST API
- `cortex-mcp` local MCP server
- `cortex serve ui` operator UI
- local store backends
- API keys, namespace boundaries, backups, logs, and release artifacts

Out of scope:

- hosted multi-tenant Cortex cloud
- enterprise SSO
- shared remote execution infrastructure

## Assets

- local memory graph contents
- claim/provenance history
- API keys and namespace grants
- backups and restore archives
- release artifacts and container images

## Trust Boundaries

- local clients to `cortexd`
- MCP clients to `cortex-mcp`
- store files on disk
- backup archives moved between machines
- published release artifacts downloaded by operators

## Main Risks

### Over-broad agent access

Risk:
- an agent receives a wildcard or multi-namespace key and can read or mutate memory outside its intended scope

Mitigations:
- namespace-scoped keys
- per-scope auth checks
- diagnostics that render scopes and namespaces without showing token values

### Accidental memory corruption

Risk:
- an import, merge, or app integration writes bad memory into the store

Mitigations:
- immutable commits
- branch/review/merge flows
- blame/history/provenance
- verified backup and restore

### Secret leakage in logs or diagnostics

Risk:
- API tokens or config secrets appear in logs, docs, or startup output

Mitigations:
- diagnostics render key names/scopes/namespaces only
- request logs do not persist auth headers
- docs use placeholder tokens only

### Supply-chain confusion during beta tags

Risk:
- prerelease tags are mistaken for stable GA artifacts

Mitigations:
- prerelease-aware publish workflow
- GitHub prerelease marking for beta/RC tags
- explicit beta quickstart and release checklist docs

### Restore and upgrade mistakes

Risk:
- operators upgrade without backup validation or restore into the wrong path

Mitigations:
- backup verify step
- upgrade docs
- startup diagnostics before serving traffic

## Beta Security Defaults

- prefer user-owned local storage
- prefer SQLite for single-node beta installs
- use least-privilege API keys
- require explicit namespace scoping for agents
- treat backups as sensitive artifacts
- do not expose `cortexd` publicly without scoped auth and network controls

## Before GA

- external security review of `cortexd` and `cortex-mcp`
- broader install-path verification on clean machines
- more field feedback from real self-hosted operators
