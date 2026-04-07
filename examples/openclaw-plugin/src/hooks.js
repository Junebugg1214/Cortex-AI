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

function _formatMountedBrainpacks(packPayloads) {
  const sections = [];
  for (const payload of packPayloads) {
    const markdown = _firstString(payload?.context_markdown, payload?.context);
    const packName = _firstString(payload?.pack, payload?.name);
    if (!markdown || !packName) {
      continue;
    }
    sections.push(`Mounted Brainpack (${packName}):\n\n${markdown}`);
  }
  return sections.join("\n\n");
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
    const mountedPacks = await runtime.service.listMountedBrainpacks(config);
    const mountedPayloads = [];
    for (const pack of mountedPacks) {
      try {
        const packSmart = typeof pack.smart === "boolean" ? pack.smart : config.smartRouting;
        mountedPayloads.push(
          await runtime.service.packContext({
            name: pack.name,
            target: config.defaultTarget,
            smart: packSmart,
            policy: _firstString(pack.policy, packSmart ? "" : "technical"),
            max_chars: Number.isFinite(Number(pack.max_chars))
              ? Number(pack.max_chars)
              : config.maxContextChars,
            project_dir: _firstString(pack.project_dir, message.project_dir),
          }),
        );
      } catch (error) {
        runtime.logger().warn?.(
          `[cortex] mounted brainpack degraded (${pack.name}): ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      }
    }
    const injected = [_formatPortableContext(payload), _formatMountedBrainpacks(mountedPayloads)]
      .filter(Boolean)
      .join("\n\n");
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
