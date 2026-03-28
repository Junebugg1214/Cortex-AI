import { resolveTurnKey, toChannelMessage } from "./identity.js";

function _firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function _formatPortableContext(turnPayload) {
  const context = turnPayload?.turn?.context || {};
  const markdown = _firstString(context.context_markdown, context.context);
  if (!markdown) {
    return "";
  }
  return `Cortex portable context:\n\n${markdown}`;
}

export function handleMessageReceived(runtime, event, ctx = {}) {
  const config = runtime.resolveConfig(ctx);
  const message = toChannelMessage(event, ctx, config);
  const turnKey = resolveTurnKey(event, ctx) || `${message.platform}:${message.conversation_id}:${message.user_id}`;
  runtime.messageCache.set(turnKey, message);
  return {};
}

export async function handleBeforePromptBuild(runtime, event, ctx = {}) {
  const config = runtime.resolveConfig(ctx);
  const turnKey = resolveTurnKey(event, ctx);
  const message =
    (turnKey && runtime.messageCache.get(turnKey)) ||
    toChannelMessage(event, ctx, config);

  try {
    const payload = await runtime.service.prepareTurn({
      message,
      target: config.defaultTarget,
      smart: config.smartRouting,
      max_chars: config.maxContextChars,
      project_dir: message.project_dir,
    });
    if (turnKey) {
      runtime.turnCache.set(turnKey, payload.turn);
    }
    const injected = _formatPortableContext(payload);
    if (!injected) {
      return {};
    }
    return { prependContext: injected };
  } catch (error) {
    runtime.lastError = error instanceof Error ? error.message : String(error);
    if (config.failOpen) {
      runtime.logger().warn?.(`[cortex] before_prompt_build degraded: ${runtime.lastError}`);
      return {};
    }
    throw error;
  }
}

export async function handleAgentEnd(runtime, event, ctx = {}) {
  const config = runtime.resolveConfig(ctx);
  if (!config.autoSeedThreads) {
    return {};
  }
  const turnKey = resolveTurnKey(event, ctx);
  const turn = turnKey ? runtime.turnCache.get(turnKey) : null;
  if (!turn) {
    return {};
  }
  try {
    await runtime.service.seedTurnMemory({
      turn,
      source: "openclaw.plugin",
      approve: false,
    });
    runtime.turnCache.delete(turnKey);
    runtime.messageCache.delete(turnKey);
  } catch (error) {
    runtime.lastError = error instanceof Error ? error.message : String(error);
    runtime.logger().warn?.(`[cortex] agent_end degraded: ${runtime.lastError}`);
    if (!config.failOpen) {
      throw error;
    }
  }
  return {};
}

