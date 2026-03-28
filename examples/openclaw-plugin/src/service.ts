import path from "node:path";
import os from "node:os";

import type { CortexPluginConfig } from "./index.js";

function expandUserPath(value: string): string {
  if (value.startsWith("~/")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

export function normalizePluginConfig(config: CortexPluginConfig) {
  return {
    ...config,
    storeDir: expandUserPath(config.storeDir ?? "~/.openclaw/cortex"),
    configPath: expandUserPath(config.configPath ?? "~/.openclaw/cortex/config.toml"),
    transport: config.transport ?? "managed-child",
    defaultTarget: config.defaultTarget ?? "chatgpt",
    smartRouting: config.smartRouting ?? true,
    autoSeedThreads: config.autoSeedThreads ?? true,
    maxContextChars: config.maxContextChars ?? 1500,
    failOpen: config.failOpen ?? true,
    requestTimeoutMs: config.requestTimeoutMs ?? 15000,
    healthCheckTimeoutMs: config.healthCheckTimeoutMs ?? 5000,
  };
}

export function buildManagedChildCommand(config: CortexPluginConfig) {
  const normalized = normalizePluginConfig(config);
  return {
    command: "cortex-mcp",
    args: ["--config", normalized.configPath],
  };
}
