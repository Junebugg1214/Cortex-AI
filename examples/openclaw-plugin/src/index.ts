export type CortexPluginConfig = {
  storeDir?: string;
  configPath?: string;
  transport?: "managed-child" | "external-mcp" | "in-process-python";
  defaultTarget?:
    | "chatgpt"
    | "claude"
    | "claude-code"
    | "codex"
    | "cursor"
    | "copilot"
    | "gemini"
    | "grok"
    | "windsurf";
  smartRouting?: boolean;
  autoSeedThreads?: boolean;
  maxContextChars?: number;
  failOpen?: boolean;
  requestTimeoutMs?: number;
  healthCheckTimeoutMs?: number;
};

// Starter scaffold only. The real plugin would wire this into OpenClaw's
// extension host, register a managed Cortex service, and install lifecycle hooks.
export default function registerCortexPlugin() {
  return {
    id: "cortex",
    displayName: "Cortex",
  };
}
