export type InboundChannelEvent = {
  platform?: string;
  workspaceId?: string;
  conversationId?: string;
  userId?: string;
  text?: string;
  displayName?: string;
  username?: string;
  phoneNumber?: string;
  email?: string;
  canonicalSubjectId?: string;
  timestamp?: string;
  metadata?: Record<string, unknown>;
};

// Starter mapper shape only. Real runtime code should normalize OpenClaw
// channel payloads into the Python ChannelMessage contract used by Cortex.
export function toChannelMessage(event: InboundChannelEvent) {
  return {
    platform: event.platform ?? "channel",
    workspace_id: event.workspaceId ?? "default",
    conversation_id: event.conversationId ?? "",
    user_id: event.userId ?? "",
    text: event.text ?? "",
    display_name: event.displayName ?? "",
    username: event.username ?? "",
    phone_number: event.phoneNumber ?? "",
    email: event.email ?? "",
    canonical_subject_id: event.canonicalSubjectId ?? "",
    timestamp: event.timestamp ?? "",
    metadata: event.metadata ?? {},
  };
}
