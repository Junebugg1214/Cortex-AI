# Upgrading Cortex

This guide assumes you are running Cortex in the supported local-first, user-owned storage model.

## Upgrade Flow

1. Export a verified backup before changing anything:

```bash
cortex backup export --store-dir .cortex --output backups/pre-upgrade.zip
cortex backup verify backups/pre-upgrade.zip
```

2. Snapshot the API contract you expect clients to use:

```bash
cortex openapi \
  --output openapi/cortex-api-v1.json \
  --compat-output openapi/cortex-api-v1-compat.json
```

3. Upgrade the Python package or rebuild the container image.

4. Run startup diagnostics before serving traffic:

```bash
cortexd --config .cortex/config.toml --check
cortex-mcp --config .cortex/config.toml --check
```

5. Run the lightweight soak harness against a disposable store:

```bash
cortex benchmark --store-dir .cortex-bench --iterations 3 --nodes 24
```

## Restore Path

If anything looks wrong after the upgrade, restore the verified archive into a clean directory:

```bash
cortex backup restore backups/pre-upgrade.zip --store-dir restored/.cortex
```

Then point `cortexd` or `cortex-mcp` at the restored directory and compare `cortexd --check` output with the
expected configuration.

## Client Compatibility

- The committed OpenAPI artifact in [openapi/cortex-api-v1.json](../openapi/cortex-api-v1.json) is the v1 contract.
- The compatibility manifest in [openapi/cortex-api-v1-compat.json](../openapi/cortex-api-v1-compat.json) captures
  the frozen path and operation set used for release checks.
- Python, TypeScript, REST, and MCP surfaces all report the same release metadata so operators can verify what is
  actually running.
