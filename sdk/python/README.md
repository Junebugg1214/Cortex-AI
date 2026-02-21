# Cortex Python SDK

Python client for the [Cortex CaaS API](https://github.com/Junebugg1214/Cortex-AI).

## Installation

```bash
pip install cortex-ai-sdk
```

## Quick Start

```python
from cortex_sdk import CortexClient

client = CortexClient(base_url="http://localhost:8421", token="your-grant-token")

# Server info (no auth required)
info = client.info()
print(info["name"], info["version"])

# Health check
health = client.health()
print(health["status"])

# Browse nodes (auto-paginating)
for node in client.nodes(limit=10):
    print(node["label"], node["confidence"])

# Get a single node
node = client.node("abc123")

# Graph stats
stats = client.stats()
print(f"{stats['node_count']} nodes, {stats['edge_count']} edges")

# Create a grant
grant = client.create_grant(audience="my-app", policy="professional")
print(grant["token"])

# List policies
for policy in client.list_policies():
    print(policy["name"])
```

## Error Handling

```python
from cortex_sdk import CortexClient, NotFoundError, AuthenticationError

client = CortexClient(token="invalid")

try:
    client.context()
except AuthenticationError as e:
    print(f"Auth failed: {e}")
except NotFoundError as e:
    print(f"Not found: {e}")
```

## API Reference

| Method | Endpoint | Auth |
|--------|----------|------|
| `info()` | GET / | No |
| `discovery()` | GET /.well-known/upai-configuration | No |
| `health()` | GET /health | No |
| `identity()` | GET /identity | No |
| `context()` | GET /context | Yes |
| `context_compact()` | GET /context/compact | Yes |
| `nodes(limit)` | GET /context/nodes | Yes |
| `node(id)` | GET /context/nodes/:id | Yes |
| `edges(limit)` | GET /context/edges | Yes |
| `stats()` | GET /context/stats | Yes |
| `versions(limit)` | GET /versions | Yes |
| `version(id)` | GET /versions/:id | Yes |
| `version_diff(a, b)` | GET /versions/diff | Yes |
| `create_grant(...)` | POST /grants | Yes |
| `list_grants()` | GET /grants | Yes |
| `revoke_grant(id)` | DELETE /grants/:id | Yes |
| `create_webhook(...)` | POST /webhooks | Yes |
| `list_webhooks()` | GET /webhooks | Yes |
| `delete_webhook(id)` | DELETE /webhooks/:id | Yes |
| `list_policies()` | GET /policies | Yes |
| `create_policy(...)` | POST /policies | Yes |
| `get_policy(name)` | GET /policies/:name | Yes |
| `delete_policy(name)` | DELETE /policies/:name | Yes |
| `metrics()` | GET /metrics | No |

## License

MIT
