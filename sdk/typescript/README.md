# Cortex TypeScript SDK

TypeScript-friendly client for the local Cortex API.

## What It Covers

- health and metadata
- metrics and structured self-hosted observability
- index status and rebuild controls
- maintenance prune status, dry-run execution, and audit history
- memory object lookup, upsert, delete, batch materialization, and claim flows
- commit, checkout, diff, branches, and log
- review, blame, and history
- query and retrieval endpoints
- memory conflict detection and resolution
- merge preview, merge resolution, and merge abort/commit flows
- OpenAPI contract discovery

## Example

```ts
import { CortexClient } from "@cortex-ai/sdk";

const client = new CortexClient("http://127.0.0.1:8766");

const health = await client.health();
const search = await client.querySearch({ query: "Project Atlas", limit: 5 });
const preview = await client.mergePreview({ otherRef: "feature/atlas", persist: true });

console.log(health.status, search.count, preview.ok);
```
