import path from "node:path";

function _isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function _firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function _get(obj, keys) {
  let current = obj;
  for (const key of keys) {
    if (!_isObject(current) && !Array.isArray(current)) {
      return undefined;
    }
    current = current[key];
  }
  return current;
}

function _extractText(value) {
  if (typeof value === "string") {
    return value.trim();
  }
  if (Array.isArray(value)) {
    return value.map((item) => _extractText(item)).filter(Boolean).join("\n").trim();
  }
  if (_isObject(value)) {
    return _firstString(
      value.text,
      value.content,
      value.body,
      value.prompt,
      _extractText(value.message),
      _extractText(value.parts),
    );
  }
  return "";
}

function _normalizeMetadata(event) {
  const metadata = _isObject(event.metadata) ? { ...event.metadata } : {};
  const known = {
    message_id: _firstString(
      event.messageId,
      event.eventId,
      _get(event, ["message", "id"]),
      _get(event, ["message", "messageId"]),
      _get(event, ["payload", "message_id"]),
    ),
    thread_id: _firstString(
      event.threadId,
      event.chatId,
      event.conversationId,
      _get(event, ["thread", "id"]),
      _get(event, ["conversation", "id"]),
      _get(event, ["chat", "id"]),
    ),
    sender_id: _firstString(
      event.userId,
      _get(event, ["sender", "id"]),
      _get(event, ["author", "id"]),
      _get(event, ["user", "id"]),
    ),
  };
  for (const [key, value] of Object.entries(known)) {
    if (value) {
      metadata[key] = value;
    }
  }
  return metadata;
}

function _resolveProjectDir(ctx, config) {
  if (config.projectDirStrategy === "explicit" && config.projectDir) {
    return config.projectDir;
  }
  if (config.projectDirStrategy === "gateway-cwd") {
    return process.cwd();
  }
  const workspace = _firstString(
    ctx?.agent?.workspaceDir,
    ctx?.agent?.cwd,
    ctx?.workspace?.cwd,
    ctx?.workspaceDir,
    ctx?.cwd,
  );
  if (workspace) {
    return path.resolve(workspace);
  }
  if (config.projectDir) {
    return config.projectDir;
  }
  return process.cwd();
}

export function resolveTurnKey(event = {}, ctx = {}) {
  return _firstString(
    event.runId,
    event.requestId,
    event.messageId,
    event.eventId,
    _get(event, ["message", "id"]),
    ctx?.runId,
    ctx?.requestId,
    ctx?.session?.id,
    ctx?.messageId,
  );
}

export function toChannelMessage(event = {}, ctx = {}, config) {
  const platform = _firstString(
    event.platform,
    event.channel,
    _get(event, ["channel", "platform"]),
    _get(ctx, ["channel", "platform"]),
    "channel",
  ).toLowerCase();

  const sender = _isObject(event.sender) ? event.sender : {};
  const author = _isObject(event.author) ? event.author : {};
  const user = _isObject(event.user) ? event.user : {};
  const identityFields = config.identityFields || {};

  return {
    platform,
    workspace_id: _firstString(
      event.workspaceId,
      _get(ctx, ["workspace", "id"]),
      _get(ctx, ["agent", "id"]),
      "default",
    ),
    conversation_id: _firstString(
      event.conversationId,
      event.threadId,
      event.chatId,
      _get(event, ["conversation", "id"]),
      _get(event, ["thread", "id"]),
      _get(event, ["chat", "id"]),
      _get(ctx, ["session", "id"]),
    ),
    user_id: _firstString(
      event.userId,
      sender.id,
      author.id,
      user.id,
      _get(event, ["message", "sender", "id"]),
    ),
    text: _firstString(
      event.text,
      _extractText(event.message),
      _extractText(event.payload),
      _extractText(event.input),
    ),
    display_name: _firstString(
      event.displayName,
      sender.displayName,
      author.displayName,
      user.displayName,
      sender.name,
      author.name,
      user.name,
    ),
    username: identityFields.username
      ? _firstString(
          event.username,
          sender.username,
          author.username,
          user.username,
          _get(event, ["message", "sender", "username"]),
        )
      : "",
    phone_number: identityFields.phoneNumber
      ? _firstString(
          event.phoneNumber,
          sender.phoneNumber,
          author.phoneNumber,
          user.phoneNumber,
          sender.phone,
          author.phone,
          user.phone,
        )
      : "",
    email: identityFields.email
      ? _firstString(
          event.email,
          sender.email,
          author.email,
          user.email,
        )
      : "",
    canonical_subject_id: identityFields.canonicalSubjectId
      ? _firstString(
          event.canonicalSubjectId,
          event.canonicalSubjectID,
          _get(event, ["identity", "canonicalSubjectId"]),
          _get(ctx, ["identity", "canonicalSubjectId"]),
        )
      : "",
    timestamp: _firstString(event.timestamp, event.sentAt, event.createdAt, new Date().toISOString()),
    project_dir: _resolveProjectDir(ctx, config),
    metadata: _normalizeMetadata(event),
  };
}

