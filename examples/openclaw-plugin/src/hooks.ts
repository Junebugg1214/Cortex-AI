import type { CortexPluginConfig } from "./index.js";
import { normalizePluginConfig } from "./service.js";

export function beforePromptBuild(config: CortexPluginConfig, event: unknown) {
  const normalized = normalizePluginConfig(config);
  return {
    stage: "before_prompt_build",
    maxContextChars: normalized.maxContextChars,
    event,
  };
}

export function afterAgentEnd(config: CortexPluginConfig, event: unknown) {
  const normalized = normalizePluginConfig(config);
  return {
    stage: "agent_end",
    autoSeedThreads: normalized.autoSeedThreads,
    failOpen: normalized.failOpen,
    event,
  };
}
