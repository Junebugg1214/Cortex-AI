# Cortex Beta Quickstart

This guide is for the first public self-hosted beta of Cortex as "Git for AI Memory."

Beta means:

- the core local runtime is expected to work for real projects
- published contracts are stable at `v1`
- operators should still expect rough edges and should keep verified backups
- prerelease tags are for evaluation, not unattended production rollouts

## Recommended Install Paths

Use one of these surfaces during beta:

1. GitHub release assets for the tagged beta or release candidate
2. Docker images from `ghcr.io/junebugg1214/cortex-ai:<tag>`
3. Local source install if you are contributing or evaluating changes from `main`

For prerelease tags like `v1.4.1-rc1`, prefer GitHub release assets or the matching Docker tag over stable package-manager
channels.

## 5-Minute Setup

1. Create a local store directory:

```bash
mkdir -p .cortex
```

2. Start from the example config:

```bash
cp docs/examples/config.toml .cortex/config.toml
```

3. Replace the example API key values before running a server.

4. Verify the runtime:

```bash
cortexd --config .cortex/config.toml --check
cortex-mcp --config .cortex/config.toml --check
```

5. Start the API:

```bash
cortexd --config .cortex/config.toml
```

6. Check health:

```bash
curl -H "Authorization: Bearer replace-me-reader" http://127.0.0.1:8766/v1/health
```

## First App Integration

- Python and TypeScript session helpers: [AGENT_QUICKSTARTS.md](AGENT_QUICKSTARTS.md)
- Full self-host setup: [SELF_HOSTING.md](SELF_HOSTING.md)
- Upgrade flow: [UPGRADING.md](UPGRADING.md)
- Operator limits, sizing, and troubleshooting: [OPERATIONS.md](OPERATIONS.md)

## Beta Safety Rules

- keep storage user-owned and local-first
- back up before upgrades: `cortex backup export --store-dir .cortex`
- keep namespace-scoped API keys narrow
- use branch + review flows for risky memory changes
- file feedback with exact version, install path, and store backend

## Feedback

Use the beta issue template when something is unclear, missing, or sharp:

- [Beta Feedback](../.github/ISSUE_TEMPLATE/beta_feedback.md)
