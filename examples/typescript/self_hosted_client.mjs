import { MemorySession, SDK_VERSION } from "@cortex-ai/sdk";

async function main() {
  const session = MemorySession.fromBaseUrl("http://127.0.0.1:8766", {
    clientOptions: {
      apiKey: "replace-me",
      namespace: "team"
    },
    sessionOptions: {
      actor: "examples/typescript"
    }
  });

  console.log("sdk", SDK_VERSION, session.sdkInfo());
  console.log("health", (await session.client.health()).status);

  await session.remember({
    label: "Project Atlas",
    nodeId: "atlas",
    brief: "Local-first memory runtime",
    aliases: ["atlas"],
    tags: ["active_priorities"],
    confidence: 0.94,
    message: "seed atlas from typescript session example"
  });

  await session.remember({
    label: "TypeScript SDK",
    nodeId: "ts-sdk",
    brief: "Programmatic Cortex client",
    tags: ["infrastructure"],
    confidence: 0.87,
    message: "seed ts sdk from typescript session example"
  });

  await session.link({
    sourceId: "atlas",
    targetId: "ts-sdk",
    relation: "depends_on"
  });

  const context = await session.searchContext({ query: "atlas", limit: 5 });
  const branch = await session.branchForTask({ task: "Atlas follow-up" });

  console.log("branch", branch.branch_name);
  console.log(context.context);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
