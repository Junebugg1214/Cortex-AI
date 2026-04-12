# Self-Hosting Cortex

Cortex is designed to stay local-first and user-owned. The self-host path is:

- run `cortexd` for REST
- run `cortex-mcp` for tool-based agent access
- keep the `.cortex` store on disk you control
- scope agents with API keys and namespaces instead of centralizing all memory

Release metadata is exposed consistently across REST, Python, TypeScript, and MCP surfaces so operators can confirm
the running package version, API generation, and frozen v1 contract hash.

## What Self-Hosting Means Right Now

Cortex is currently strongest as:

- a single-user local runtime
- a small-team, operator-managed self-host deployment
- a portable Mind layer that you wire into external runtimes deliberately

Cortex is not currently positioned as:

- a hosted multi-tenant Cortex cloud
- a public internet service with automatic enterprise controls
- a substitute for your own reverse proxy, TLS, network policy, and operator practices

## Deployment Modes

### `local-single-user`

This is the default mode.

Use it when:

- Cortex runs on the same machine you use directly
- REST/UI/Manus surfaces stay on loopback
- local trust and user-owned storage are the primary goals

### `hosted-service`

Use this only when you are intentionally exposing Cortex as a self-hosted service.

Hosted-service mode expects:

- configured API keys before binding beyond loopback
- HTTPS terminated by a reverse proxy you control
- scoped API keys instead of wildcard grants whenever possible
- pinned namespaces for shared Manus bridges or team-specific runtimes
- operators who understand the warnings emitted by `cortex serve ... --check`

For the public beta rollout, pair this guide with:

- [BETA_QUICKSTART.md](BETA_QUICKSTART.md)
- [OPERATIONS.md](OPERATIONS.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)

## Shared `config.toml`

By default, Cortex looks for `config.toml` inside your store directory, usually `.cortex/config.toml`.

Example:

```toml
[runtime]
store_dir = ".cortex"

[server]
host = "127.0.0.1"
port = 8766

[mcp]
namespace = "team"

[[auth.keys]]
name = "reader"
token = "replace-me-reader"
scopes = ["read"]
namespaces = ["team"]

[[auth.keys]]
name = "writer"
token = "replace-me-writer"
scopes = ["write", "branch", "merge", "index"]
namespaces = ["team"]

[[auth.keys]]
name = "maintainer"
token = "replace-me-maintainer"
scopes = ["prune"]
namespaces = ["*"]
```

## Scope Model

- `read`: GET endpoints, checkout, diff, review, blame, history, queries
- `write`: object writes and full-graph commit paths
- `branch`: branch creation and switching
- `merge`: merge preview, merge resolution, merge commit, merge abort
- `index`: index rebuild and index inspection
- `prune`: prune status, audit, and prune execution

Namespace-scoped keys can only act on namespaces they own. If a key is pinned to exactly one namespace, Cortex will
use that namespace by default when the request does not provide one.

## Agent Runtime Surface

The agent runtime is exposed consistently across REST, Python, TypeScript, and MCP:

- `GET /v1/agent/status`
- `POST /v1/agent/monitor/run`
- `POST /v1/agent/compile`
- `POST /v1/agent/dispatch`
- `POST /v1/agent/schedule`
- `POST /v1/agent/conflicts/review`

### REST Example

```bash
curl -sS \
  -H "Authorization: Bearer replace-me" \
  -H "X-Cortex-Namespace: team" \
  http://127.0.0.1:8766/v1/agent/status

curl -sS \
  -X POST \
  -H "Authorization: Bearer replace-me" \
  -H "X-Cortex-Namespace: team" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8766/v1/agent/compile \
  -d '{
    "mind_id": "personal",
    "audience_id": "recruiter",
    "output_format": "cv",
    "output_dir": "./output"
  }'
```

### Python Client Example

```python
from cortex.client import CortexClient

client = CortexClient(
    "http://127.0.0.1:8766",
    api_key="replace-me",
    namespace="team",
)

status = client.agent_status()
result = client.agent_compile(
    mind_id="personal",
    audience_id="recruiter",
    output_format="cv",
    output_dir="./output",
)

print(status["pending_count"], result["rule"]["output_format"])
```

### TypeScript Client Example

```ts
import { CortexClient } from "@cortex-ai/sdk";

const client = new CortexClient("http://127.0.0.1:8766", {
  apiKey: "replace-me",
  namespace: "team"
});

const status = await client.agentStatus();
const result = await client.agentCompile({
  mindId: "personal",
  audienceId: "recruiter",
  outputFormat: "cv",
  outputDir: "./output"
});

console.log(status.pending_count, result.rule.output_format);
```

### Review Queued Conflicts

```bash
curl -sS \
  -X POST \
  -H "Authorization: Bearer replace-me" \
  -H "X-Cortex-Namespace: team" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8766/v1/agent/conflicts/review \
  -d '{
    "decisions": [
      { "conflict_id": "replace-me", "candidate_rank": 1 }
    ]
  }'
```

```python
monitor = client.agent_monitor_run(mind_id="career")
if monitor["proposals"]:
    client.agent_review_conflicts(
        decisions=[
            {
                "conflict_id": monitor["proposals"][0]["conflict_id"],
                "candidate_rank": 1,
            }
        ]
    )
```

## Startup Diagnostics

Use `--check` before you start a process for real:

```bash
cortex serve api --config .cortex/config.toml --check
cortex serve mcp --config .cortex/config.toml --check
cortex serve manus --config .cortex/config.toml --check
cortex serve ui --config .cortex/config.toml --check

# direct entrypoints
cortexd --config .cortex/config.toml --check
cortex-mcp --config .cortex/config.toml --check
```

That prints the resolved store directory, backend, auth summary, namespace defaults, and warnings such as running in
local trust mode with no API keys configured.

For hosted-service mode, treat warnings about bind scope, missing auth, wildcard namespaces, and reverse proxies as
deployment blockers rather than optional suggestions.

## Hosted-Service Checklist

Before you expose Cortex beyond localhost:

- configure real API keys in `.cortex/config.toml`
- verify `cortex serve api --check` and `cortex serve manus --check`
- terminate HTTPS at a reverse proxy you control
- prefer one namespace per bridge or workflow
- keep the UI on trusted networks only
- export and verify a backup before first exposure

## Backup and Restore

Export a verified archive:

```bash
cortex backup export --store-dir .cortex --output backups/cortex-store.zip
```

Verify it later:

```bash
cortex backup verify backups/cortex-store.zip
```

Restore into a fresh directory:

```bash
cortex backup restore backups/cortex-store.zip --store-dir restored/.cortex
```

Overwrite an existing directory only when you mean it:

```bash
cortex backup restore backups/cortex-store.zip --store-dir .cortex --force
```

## Docker

The repo ships with an operator-oriented local image and compose file:

```bash
docker compose up --build
```

That mounts the local `./.cortex` directory into the container, runs `cortexd`, and exposes a container healthcheck
against `/v1/health`.

The image defaults to:

```bash
cortexd --config /data/.cortex/config.toml
```

## MCP Client Example

See [config.toml example](examples/config.toml) and
[Claude Desktop example](examples/claude_desktop_mcp.json).

The important rule is to keep the store local and only hand each agent the namespace and scopes it needs.

## Reference Examples

- Python client: [examples/python/self_hosted_client.py](../examples/python/self_hosted_client.py)
- TypeScript client: [examples/typescript/self_hosted_client.mjs](../examples/typescript/self_hosted_client.mjs)
- Agent quickstarts: [AGENT_QUICKSTARTS.md](AGENT_QUICKSTARTS.md)
- MCP JSON-RPC flow: [examples/mcp/README.md](../examples/mcp/README.md)

## Upgrade and Release

- Beta quickstart: [BETA_QUICKSTART.md](BETA_QUICKSTART.md)
- Operations guide: [OPERATIONS.md](OPERATIONS.md)
- Threat model: [THREAT_MODEL.md](THREAT_MODEL.md)
- Upgrade guide: [UPGRADING.md](UPGRADING.md)
- Release checklist: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)
