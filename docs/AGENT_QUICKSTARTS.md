# Agent Quickstarts

Cortex now ships a higher-level `MemorySession` adoption layer on top of the stable REST and SDK surfaces.

Use it when you want app and agent code to do four common things without custom glue:

- `remember(...)`
- `search_context(...)`
- `branch_for_task(...)`
- `commit_if_review_passes(...)`

## Python App Loop

```python
from cortex.session import MemorySession

session = MemorySession.from_base_url(
    "http://127.0.0.1:8766",
    api_key="replace-me",
    namespace="team",
    actor="agent/runtime",
)

search = session.search_context(query="Project Atlas", limit=5)
print(search["context"])

session.remember(
    label="Project Atlas",
    node_id="atlas",
    brief="Local-first memory runtime",
    tags=["active_priorities"],
)

branch = session.branch_for_task("Atlas investigation")
print(branch["branch_name"])
```

Reference files:

- [examples/python/self_hosted_client.py](../examples/python/self_hosted_client.py)
- [examples/python/agent_memory_loop.py](../examples/python/agent_memory_loop.py)

## TypeScript App Loop

```ts
import { MemorySession } from "@cortex-ai/sdk";

const session = MemorySession.fromBaseUrl("http://127.0.0.1:8766", {
  clientOptions: { apiKey: "replace-me", namespace: "team" },
  sessionOptions: { actor: "agent/runtime" }
});

const search = await session.searchContext({ query: "Project Atlas", limit: 5 });
console.log(search.context);

await session.remember({
  label: "Project Atlas",
  nodeId: "atlas",
  brief: "Local-first memory runtime",
  tags: ["active_priorities"]
});

const branch = await session.branchForTask({ task: "Atlas investigation" });
console.log(branch.branch_name);
```

Reference files:

- [examples/typescript/self_hosted_client.mjs](../examples/typescript/self_hosted_client.mjs)
- [examples/typescript/agent_memory_loop.mjs](../examples/typescript/agent_memory_loop.mjs)

## LangGraph-Style State Recipe

The easiest pattern is to keep Cortex outside your graph state machine and store only the rendered memory block or
the IDs you want to revisit later.

1. At the start of a step, call `search_context(...)`.
2. Put `search["context"]` into your model input.
3. After the step, summarize the durable outcome.
4. Call `remember(...)` or `remember_many(...)`.
5. For risky changes, create a task branch with `branch_for_task(...)`.

## Branch Per Task

Use task branches when an agent is about to do something exploratory:

```python
branch = session.branch_for_task("Atlas pricing experiments")
```

That gives you a predictable branch name and keeps memory experiments isolated until you review or merge them.

## Commit After Review

For graph-oriented workflows that still produce a full graph payload:

```python
result = session.commit_if_review_passes(
    graph=graph_payload,
    message="refresh project memory",
    against="main",
)
```

That runs the existing review policy first and only commits when the review passes.

## MCP Runtime

If your agent stack prefers tools instead of direct SDK calls, Cortex still supports the same user-owned store over
MCP:

- [examples/mcp/README.md](../examples/mcp/README.md)
- [docs/examples/claude_desktop_mcp.json](examples/claude_desktop_mcp.json)

For portability-first use, the human still curates context with CLI commands like `cortex portable`,
`cortex remember`, `cortex scan`, and `cortex sync --smart`. The AI tool then reads live context over MCP with:

- `portability_context` to fetch the current routed slice for `claude-code`, `codex`, `cursor`, `copilot`, `gemini`,
  `windsurf`, `claude`, `chatgpt`, or `grok`
- `portability_scan` to inspect what each tool currently knows
- `portability_status` to surface stale or missing context
- `portability_audit` to detect cross-tool drift
