# Release Checklist

## Trigger

- Push a version tag like `v1.4.1` to trigger the GitHub release workflow in [`.github/workflows/publish.yml`](../.github/workflows/publish.yml).
- Confirm the publish environments and secrets are ready:
  - PyPI trusted publishing or environment approval
  - `NPM_TOKEN` for the TypeScript package
  - `GITHUB_TOKEN` package permissions for GHCR

## Release Notes

- Regenerate the release notes and JSON manifest:

```bash
cortex release-notes \
  --output dist/release-notes.md \
  --manifest-output dist/release-manifest.json
```

- Confirm the notes mention the expected Python package, TypeScript package, Docker image, and contract hash.

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
- Run `python -m build` and verify the wheel installs cleanly.
- Run `cd sdk/typescript && npm pack`.

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
- Confirm `cortexd --help`, `cortex-mcp --help`, and `cortex-bench --help` work from the built wheel.
