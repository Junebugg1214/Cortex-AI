# TypeScript SDK Quickstart

Get up and running with the Cortex TypeScript SDK in 5 minutes.

## Prerequisites

1. **Install the SDK:**

```bash
npm install @cortex_ai/sdk
```

Zero runtime dependencies — uses native `fetch` only.

2. **Start the Cortex server** (requires Python + `cortex-identity`):

```bash
cortex serve context.json --port 8421
```

3. **Create a grant token:**

```bash
cortex grant --create --audience "my-app" --policy professional
```

Copy the token from the output.

## Connect to the Server

### ESM (recommended)

```typescript
import { CortexClient } from '@cortex_ai/sdk';

const client = new CortexClient({
  baseUrl: 'http://localhost:8421',
  token: 'your-grant-token-here',
});
```

### CommonJS

```javascript
const { CortexClient } = require('@cortex_ai/sdk');

const client = new CortexClient({
  baseUrl: 'http://localhost:8421',
  token: 'your-grant-token-here',
});
```

## Check Server Health

These endpoints don't require authentication:

```typescript
// Server info
const info = await client.info();
console.log(`Server: ${info.name} v${info.version}`);
// → Server: cortex-caas v1.0.0

// Health check
const health = await client.health();
console.log(`Status: ${health.status}`);
// → Status: healthy

// UPAI discovery document
const discovery = await client.discovery();
console.log('Endpoints:', Object.keys(discovery.endpoints ?? {}));
```

## Explore the Knowledge Graph

```typescript
// Graph statistics
const stats = await client.stats();
console.log(`Nodes: ${stats.node_count}, Edges: ${stats.edge_count}`);
// → Nodes: 142, Edges: 87

// Iterate over nodes (async generator, auto-paginated)
for await (const node of client.nodes(5)) {
  console.log(`  [${node.tags[0]}] ${node.label} (${node.confidence})`);
}
// → [technical_expertise] Python (0.95)
// → [professional_context] Senior Engineer at Acme Corp (0.90)

// Fetch a single node by ID
const node = await client.node('node-id-here');
console.log(node.label, node.brief ?? '');
```

## Get Context as Markdown

```typescript
// Compact markdown summary (great for LLM system prompts)
const markdown = await client.contextCompact();
console.log(markdown.slice(0, 200));
// → ## Identity
// → - Name: Jane Doe
// → ...
```

## Create and Manage Grants

```typescript
// Create a grant for another consumer
const grant = await client.createGrant({
  audience: 'my-chatbot',
  policy: 'technical',
  ttl_hours: 48,
  scopes: ['context:read', 'versions:read'],
});
console.log(`Grant ID: ${grant.grant_id}`);
console.log(`Token: ${grant.token}`);

// List all active grants
const grants = await client.listGrants();
for (const g of grants) {
  console.log(`  ${g.grant_id} → ${g.audience} (policy: ${g.policy})`);
}

// Revoke a grant
await client.revokeGrant(grant.grant_id);
```

## Stream with SSE

Connect to the server-sent events endpoint for real-time updates:

```typescript
// Native EventSource (browser or Node 18+)
const es = new EventSource('http://localhost:8421/events');

es.addEventListener('context.updated', (event) => {
  const data = JSON.parse(event.data);
  console.log('Context updated:', data);
});

es.addEventListener('grant.created', (event) => {
  console.log('New grant:', JSON.parse(event.data));
});

// Replay missed events with Last-Event-ID header
const esReplay = new EventSource('http://localhost:8421/events', {
  headers: { 'Last-Event-ID': '42' },
} as EventSourceInit);
```

## Browse Version History

```typescript
// Iterate over version snapshots
for await (const ver of client.versions(3)) {
  console.log(`  ${ver.version_id.slice(0, 8)}  ${ver.message}  (${ver.node_count} nodes)`);
}

// Diff two versions
const diff = await client.versionDiff('version-a-id', 'version-b-id');
console.log(`Added: ${diff.added_nodes.length}, Removed: ${diff.removed_nodes.length}`);
```

## Error Handling

The SDK throws typed exceptions:

```typescript
import {
  AuthenticationError,
  ForbiddenError,
  NotFoundError,
  RateLimitError,
  ValidationError,
  ServerError,
  CortexSDKError,
} from '@cortex_ai/sdk';

try {
  await client.node('nonexistent-id');
} catch (err) {
  if (err instanceof NotFoundError) {
    console.log(`Not found: ${err.message}`);
  } else if (err instanceof AuthenticationError) {
    console.log('Bad or expired token — create a new grant');
  } else if (err instanceof RateLimitError) {
    console.log('Rate limited — back off and retry');
  } else if (err instanceof CortexSDKError) {
    console.log(`SDK error (${err.statusCode}): ${err.message}`);
  }
}
```

## TypeScript Types

The SDK exports all resource interfaces for full type safety:

```typescript
import type {
  CortexClientOptions,
  ServerInfo,
  HealthCheck,
  ContextNode,
  ContextEdge,
  GraphStats,
  Grant,
  CreateGrantOptions,
  Webhook,
  CreateWebhookOptions,
  Policy,
  VersionSnapshot,
  VersionDiff,
} from '@cortex_ai/sdk';
```

## Full API Reference

| Method | Returns | Description |
|--------|---------|-------------|
| `info()` | `ServerInfo` | Server info (no auth) |
| `health()` | `HealthCheck` | Health check (no auth) |
| `discovery()` | `Record` | UPAI discovery document (no auth) |
| `identity()` | `Record` | W3C DID Document (no auth) |
| `context()` | `Record` | Full signed graph |
| `contextCompact()` | `string` | Markdown summary |
| `nodes(limit?)` | `AsyncGenerator<ContextNode>` | Auto-paginating node stream |
| `node(nodeId)` | `ContextNode` | Single node by ID |
| `edges(limit?)` | `AsyncGenerator<ContextEdge>` | Auto-paginating edge stream |
| `stats()` | `GraphStats` | Graph statistics |
| `versions(limit?)` | `AsyncGenerator<VersionSnapshot>` | Version history stream |
| `version(versionId)` | `VersionSnapshot` | Single version snapshot |
| `versionDiff(a, b)` | `VersionDiff` | Diff two versions |
| `createGrant(options)` | `Grant` | Create grant token |
| `listGrants()` | `Grant[]` | List all grants |
| `revokeGrant(grantId)` | `Record` | Revoke a grant |
| `createWebhook(options)` | `Webhook` | Register webhook |
| `listWebhooks()` | `Webhook[]` | List all webhooks |
| `deleteWebhook(webhookId)` | `Record` | Delete webhook |
| `listPolicies()` | `Policy[]` | List disclosure policies |
| `createPolicy(name, opts?)` | `Policy` | Create custom policy |
| `getPolicy(name)` | `Policy` | Get single policy |
| `deletePolicy(name)` | `Record` | Delete custom policy |
| `metrics()` | `string` | Prometheus metrics (no auth) |

## Next Steps

- [Python SDK Quickstart](quickstart-python.md) — same flow in Python
- [CLI Walkthrough](cli-walkthrough.md) — explore all CLI commands
- [Error Reference](error-guide.md) — all 17 UPAI error codes explained
- [Interactive API Docs](http://localhost:8421/docs) — Swagger UI (start server first)
