# Cortex TypeScript SDK

TypeScript-friendly client for the local Cortex API.

## Install

```bash
npm install @cortex-ai/sdk
```

## What It Covers

- health and metadata
- metrics and structured self-hosted observability
- release and contract metadata for self-hosted runtimes
- index status and rebuild controls
- maintenance prune status, dry-run execution, and audit history
- memory object lookup, upsert, delete, batch materialization, and claim flows
- high-level `MemorySession` helpers for `remember`, `searchContext`, task branches, and review-gated commits
- commit, checkout, diff, branches, and log
- review, blame, and history
- query and retrieval endpoints
- memory conflict detection and resolution
- agent monitor, compile, dispatch, schedule, review, and status flows
- merge preview, merge resolution, and merge abort/commit flows
- OpenAPI contract discovery

## Example

```ts
import { MemorySession, SDK_VERSION } from "@cortex-ai/sdk";

const session = MemorySession.fromBaseUrl("http://127.0.0.1:8766");

console.log("sdk", SDK_VERSION, session.sdkInfo());

const health = await session.client.health();
const search = await session.searchContext({ query: "Project Atlas", limit: 5 });
const branch = await session.branchForTask({ task: "Atlas investigation" });

console.log(health.status, search.context, branch.branch_name);
```

For the matching OpenAPI contract, Docker flow, backup/restore workflow, and MCP examples, see the root
[self-hosting guide](../../docs/SELF_HOSTING.md) and [agent quickstarts](../../docs/AGENT_QUICKSTARTS.md).

## Agent API Example

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

console.log(status.pending_count, result.rule.output_format, result.artifacts);
```

## Review Queued Conflicts

```ts
const monitor = await client.agentMonitorRun({ mindId: "career" });

if (monitor.proposals?.length) {
  const proposal = monitor.proposals[0];
  await client.agentReviewConflicts({
    decisions: [{ conflict_id: proposal.conflict_id, candidate_rank: 1 }]
  });
}
```
