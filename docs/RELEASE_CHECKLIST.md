# Release Checklist

## Contract

- Regenerate the committed OpenAPI artifact:

```bash
cortex openapi \
  --output openapi/cortex-api-v1.json \
  --compat-output openapi/cortex-api-v1-compat.json
```

- Confirm the compatibility snapshot only changes when the v1 contract intentionally changes.

## Validation

- Run targeted packaging and release tests.
- Run the full `pytest -q` suite.
- Run `ruff check` and `ruff format --check`.
- Run `python -m compileall cortex`.
- Run `node --check sdk/typescript/dist/index.js`.

## Self-Host Packaging

- Build the container image: `docker build -t cortex-ai/cortex-selfhost:local .`
- Verify compose starts cleanly: `docker compose up --build`
- Confirm `GET /v1/health` returns `status=ok`.
- Run `cortexd --config .cortex/config.toml --check`.
- Run `cortex-mcp --config .cortex/config.toml --check`.

## Backup and Restore

- Export and verify a backup archive.
- Restore the archive into a fresh directory and confirm parity.

## SDK and Example Surface

- Smoke-check the Python example in [examples/python/self_hosted_client.py](../examples/python/self_hosted_client.py).
- Smoke-check the TypeScript example in [examples/typescript/self_hosted_client.mjs](../examples/typescript/self_hosted_client.mjs).
- Smoke-check the MCP JSON-RPC flow in [examples/mcp/README.md](../examples/mcp/README.md).
