# Python SDK Quickstart

Get up and running with the Cortex Python SDK in 5 minutes.

## Prerequisites

1. **Install Cortex** and the Python SDK:

```bash
pip install cortex-identity
```

The SDK is included — no extra packages required (zero dependencies, stdlib only).

2. **Start the server** with a context graph:

```bash
cortex serve context.json --port 8421
```

> Don't have a context file yet? Run `cortex extract chatgpt-export.zip -o context.json` to build one from a ChatGPT export, or use any JSON file from the `examples/` directory.

3. **Create a grant token** (in another terminal):

```bash
cortex grant --create --audience "my-script" --policy professional
```

Copy the token from the output — you'll need it below.

## Connect to the Server

```python
from cortex_sdk import CortexClient

client = CortexClient(
    base_url="http://localhost:8421",
    token="your-grant-token-here",
)
```

## Check Server Health

These endpoints don't require authentication:

```python
# Server info
info = client.info()
print(f"Server: {info['name']} v{info['version']}")
# → Server: cortex-caas v1.0.0

# Health check
health = client.health()
print(f"Status: {health['status']}")
# → Status: healthy

# UPAI discovery document
discovery = client.discovery()
print(f"Endpoints: {list(discovery.get('endpoints', {}).keys())}")
```

## Explore the Knowledge Graph

```python
# Graph statistics
stats = client.stats()
print(f"Nodes: {stats['node_count']}, Edges: {stats['edge_count']}")
# → Nodes: 142, Edges: 87

# Iterate over nodes (auto-paginated)
for node in client.nodes(limit=5):
    print(f"  [{node['tags'][0]}] {node['label']} (confidence: {node['confidence']})")
# → [technical_expertise] Python (confidence: 0.95)
# → [professional_context] Senior Engineer at Acme Corp (confidence: 0.90)
# → ...

# Fetch a single node by ID
node = client.node("node-id-here")
print(node["label"], node.get("brief", ""))
```

## Get Context as Markdown

```python
# Compact markdown summary (great for LLM system prompts)
markdown = client.context_compact()
print(markdown[:200])
# → ## Identity
# → - Name: Jane Doe
# → - Role: Senior Engineer
# → ...
```

## Create and Manage Grants

```python
# Create a grant for another consumer
grant = client.create_grant(
    audience="my-chatbot",
    policy="technical",   # only share technical skills
    ttl_hours=48,
    scopes=["context:read", "versions:read"],
)
print(f"Grant ID: {grant['grant_id']}")
print(f"Token: {grant['token']}")

# List all active grants
for g in client.list_grants():
    print(f"  {g['grant_id']} → {g['audience']} (policy: {g['policy']})")

# Revoke a grant
client.revoke_grant(grant["grant_id"])
```

## Browse Version History

```python
# Iterate over version snapshots
for ver in client.versions(limit=3):
    print(f"  {ver['version_id'][:8]}  {ver['message']}  ({ver['node_count']} nodes)")

# Diff two versions
diff = client.version_diff("version-a-id", "version-b-id")
print(f"Added: {len(diff['added_nodes'])}, Removed: {len(diff['removed_nodes'])}")
```

## Error Handling

The SDK raises typed exceptions for HTTP errors:

```python
from cortex_sdk.exceptions import (
    AuthenticationError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    ServerError,
    CortexSDKError,
)

try:
    client.node("nonexistent-id")
except NotFoundError as e:
    print(f"Not found: {e}")
except AuthenticationError:
    print("Bad or expired token — create a new grant")
except CortexSDKError as e:
    print(f"SDK error: {e}")
```

## Full API Reference

| Method | Description |
|--------|-------------|
| `info()` | Server info (no auth) |
| `health()` | Health check (no auth) |
| `discovery()` | UPAI discovery document (no auth) |
| `identity()` | W3C DID Document (no auth) |
| `context()` | Full signed graph |
| `context_compact()` | Markdown summary |
| `nodes(limit=20)` | Auto-paginating node iterator |
| `node(node_id)` | Single node by ID |
| `edges(limit=20)` | Auto-paginating edge iterator |
| `stats()` | Graph statistics |
| `versions(limit=20)` | Auto-paginating version iterator |
| `version(version_id)` | Single version snapshot |
| `version_diff(a, b)` | Diff two versions |
| `create_grant(audience, ...)` | Create grant token |
| `list_grants()` | List all grants |
| `revoke_grant(grant_id)` | Revoke a grant |
| `create_webhook(url, events)` | Register webhook |
| `list_webhooks()` | List all webhooks |
| `delete_webhook(webhook_id)` | Delete webhook |
| `list_policies()` | List disclosure policies |
| `create_policy(name, ...)` | Create custom policy |
| `get_policy(name)` | Get single policy |
| `delete_policy(name)` | Delete custom policy |
| `metrics()` | Prometheus metrics (no auth) |

## Next Steps

- [TypeScript SDK Quickstart](quickstart-typescript.md) — same flow in TypeScript
- [CLI Walkthrough](cli-walkthrough.md) — explore all CLI commands
- [Error Reference](error-guide.md) — all 17 UPAI error codes explained
- [Interactive API Docs](http://localhost:8421/docs) — Swagger UI (start server first)
