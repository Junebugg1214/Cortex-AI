# SDK Quickstart Example

Demonstrates the Python SDK client for interacting with a Cortex CaaS server.

## Prerequisites

```bash
pip install cortex-ai-sdk

# Start a server
cortex serve context.json
```

## Run

```bash
python examples/sdk-quickstart/main.py
```

## API Surface

| Method | Description |
|--------|-------------|
| `client.info()` | Server info |
| `client.health()` | Health check |
| `client.stats()` | Graph statistics |
| `client.nodes()` | Paginated node listing |
| `client.node(id)` | Single node by ID |
| `client.edges()` | Paginated edge listing |
| `client.create_grant(...)` | Issue grant token |
| `client.create_webhook(...)` | Register webhook |
