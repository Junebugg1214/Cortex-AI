# @cortex_ai/sdk

TypeScript SDK for the [Cortex CaaS](https://github.com/Junebugg1214/Cortex-AI) (Context-as-a-Service) API.

Zero runtime dependencies. Works with Node.js 18+ using native `fetch`.

## Install

```bash
npm install @cortex_ai/sdk
```

## Quick Start

```typescript
import { CortexClient } from "@cortex_ai/sdk";

const client = new CortexClient("http://localhost:8100", {
  bearer: "your-token",
});

// Store a memory
await client.ingest({
  subject: "did:cortex:abc123",
  predicate: "learned",
  object: "TypeScript SDK usage",
});

// Query memories
const results = await client.query("did:cortex:abc123", {
  predicate: "learned",
});

// Subscribe to real-time updates via SSE
const stream = client.subscribe("did:cortex:abc123");
for await (const event of stream) {
  console.log(event);
}
```

## Features

- Full CaaS API coverage (ingest, query, subscribe, webhooks, credentials)
- SSE streaming with automatic reconnection and `Last-Event-ID` replay
- Bearer token and OAuth2 client-credentials authentication
- Pagination helpers
- ESM and CommonJS dual-build
- Zero runtime dependencies

## Documentation

See the [main repository](https://github.com/Junebugg1214/Cortex-AI) for full documentation, protocol spec, and server setup.

## License

MIT
