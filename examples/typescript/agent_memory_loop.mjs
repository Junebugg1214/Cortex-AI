import { MemorySession } from "@cortex-ai/sdk";

function callModel(userMessage, memoryContext) {
  return `Model reply for: ${userMessage}\n\nUsing memory:\n${memoryContext}`;
}

function summarizeTurn(userMessage, assistantReply) {
  return `User asked about '${userMessage}'. Assistant replied with '${assistantReply.slice(0, 80)}'.`;
}

async function runTurn(userMessage) {
  const session = MemorySession.fromBaseUrl("http://127.0.0.1:8766", {
    clientOptions: {
      apiKey: "replace-me",
      namespace: "team"
    },
    sessionOptions: {
      actor: "examples/agent-loop"
    }
  });

  const search = await session.searchContext({ query: userMessage, limit: 5 });
  const assistantReply = callModel(userMessage, search.context);
  const summary = summarizeTurn(userMessage, assistantReply);

  await session.remember({
    label: `Conversation: ${userMessage.slice(0, 40)}`,
    brief: summary,
    tags: ["conversation_memory", "agent_runtime"],
    message: `remember turn: ${userMessage.slice(0, 40)}`
  });

  console.log(assistantReply);
}

runTurn("What do we already know about Project Atlas?").catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
