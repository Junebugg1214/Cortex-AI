import { CortexClient, SDK_VERSION } from "@cortex-ai/sdk";

async function main() {
  const client = new CortexClient("http://127.0.0.1:8766", {
    apiKey: "replace-me",
    namespace: "team"
  });

  console.log("sdk", SDK_VERSION, client.sdkInfo());
  console.log("health", (await client.health()).status);

  await client.upsertNode({
    node: {
      id: "atlas",
      label: "Project Atlas",
      aliases: ["atlas"],
      tags: ["active_priorities"],
      confidence: 0.94
    },
    message: "seed atlas from typescript example"
  });

  const results = await client.querySearch({ query: "atlas", limit: 5 });
  console.log("query count", results.count);
  console.log("top result", results.results[0].node.label);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
