import { handleAgentEnd, handleBeforePromptBuild, handleMessageReceived } from "./hooks.js";
import { createCortexMcpService, normalizePluginConfig, readPluginConfig } from "./service.js";

export function createCortexPluginRuntime(api, initialConfig = {}) {
  const runtime = {
    api,
    initialConfig,
    messageCache: new Map(),
    turnCache: new Map(),
    lastError: "",
    logger() {
      return api?.logger || console;
    },
    resolveConfig(ctx = null, overrides = {}) {
      const merged = {
        ...readPluginConfig(api, ctx),
        ...initialConfig,
        ...overrides,
      };
      return normalizePluginConfig(merged);
    },
  };
  runtime.service = createCortexMcpService(api, initialConfig);
  return runtime;
}

function register(api) {
  const runtime = createCortexPluginRuntime(api);

  api.registerService({
    id: "cortex",
    start: async () => runtime.service.start(),
    stop: async () => runtime.service.stop(),
  });

  api.on(
    "gateway_start",
    async (_event, ctx) => runtime.service.start(ctx),
    { priority: 20 },
  );
  api.on(
    "message_received",
    async (event, ctx) => handleMessageReceived(runtime, event, ctx),
    { priority: 20 },
  );
  api.on(
    "before_prompt_build",
    async (event, ctx) => handleBeforePromptBuild(runtime, event, ctx),
    { priority: 20 },
  );
  api.on(
    "agent_end",
    async (event, ctx) => handleAgentEnd(runtime, event, ctx),
    { priority: 0 },
  );
  api.on(
    "gateway_stop",
    async () => {
      await runtime.service.stop();
      runtime.turnCache.clear();
      runtime.messageCache.clear();
      return {};
    },
    { priority: -20 },
  );
}

export { normalizePluginConfig };

export default {
  id: "cortexai-openclaw",
  name: "CortexAI OpenClaw",
  register,
};
