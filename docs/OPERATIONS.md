# Cortex Operations

This guide captures the default operating guidance for the self-hosted beta.

## Sizing Guidance

Start with:

- 1 local or small VM node
- SQLite-backed store
- SSD-backed disk
- enough space for the store, logs, backups, and index artifacts

Reasonable beta starting points:

- small project: a few thousand memory objects and a single namespace
- team project: tens of thousands of memory objects, multiple namespaces, regular backups
- heavier evaluation: run the benchmark harness before sharing the store across many agents

Use the benchmark harness to measure your own workload:

```bash
cortex-bench --store-dir .cortex-bench --iterations 3 --nodes 24
```

## Recommended Limits

For beta, prefer:

- one write path at a time per store
- explicit namespace scoping for every agent key
- small batch writes rather than huge graph rewrites
- periodic backup export after major migrations or merges

## Startup Checklist

```bash
cortex serve api --config .cortex/config.toml --check
cortex serve mcp --config .cortex/config.toml --check
cortex serve manus --config .cortex/config.toml --check
```

Verify:

- expected store directory
- expected backend
- expected runtime mode
- expected bind scope
- expected namespace scope
- expected auth key names and scopes
- no warnings you do not understand

## Troubleshooting

### `Unauthorized` from the API

- confirm the `Authorization: Bearer <token>` header
- confirm the key has the required scope
- confirm the namespace is allowed by the key

### `Forbidden` for a namespace

- send `X-Cortex-Namespace`
- or use a single-namespace key so Cortex can infer it safely

### Search looks stale

- check `GET /v1/index/status`
- run `POST /v1/index/rebuild`
- inspect `/v1/metrics` for index lag

### Upgrade feels risky

- export a verified backup first
- restore into a fresh directory
- compare `cortexd --check` output before switching traffic

### MCP client behaves differently from REST

- confirm both are pointed at the same store
- confirm the MCP namespace matches the REST namespace
- prefer scoped keys instead of wildcard keys for agent sessions

## Logs and Metrics

Structured request logs are written under the store directory:

- `logs/cortexd.jsonl`

Operational endpoints:

- `GET /v1/health`
- `GET /v1/meta`
- `GET /v1/metrics`
- `GET /v1/index/status`
- `GET /v1/prune/status`

## Backup and Restore

```bash
cortex backup export --store-dir .cortex --output backups/pre-change.zip
cortex backup verify backups/pre-change.zip
cortex backup restore backups/pre-change.zip --store-dir restored/.cortex
```

Treat backup verification as mandatory before upgrades and before any broad beta rollout.
