# Self-Hosting Cortex

Cortex is designed to stay local-first and user-owned. The self-host path is:

- run `cortexd` for REST
- run `cortex-mcp` for tool-based agent access
- keep the `.cortex` store on disk you control
- scope agents with API keys and namespaces instead of centralizing all memory

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

## Startup Diagnostics

Use `--check` before you start a process for real:

```bash
cortex server --config .cortex/config.toml --check
cortex mcp --config .cortex/config.toml --check

# direct entrypoints
cortexd --config .cortex/config.toml --check
cortex-mcp --config .cortex/config.toml --check
```

That prints the resolved store directory, backend, auth summary, namespace defaults, and warnings such as running in
local trust mode with no API keys configured.

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

The repo ships with a simple compose file:

```bash
docker compose up --build
```

That mounts the local `./.cortex` directory into the container and runs:

```bash
cortex server --config /data/.cortex/config.toml
```

## MCP Client Example

See [config.toml example](examples/config.toml) and
[Claude Desktop example](examples/claude_desktop_mcp.json).

The important rule is to keep the store local and only hand each agent the namespace and scopes it needs.
