/**
 * TypeScript interfaces for CaaS API resources.
 */

export interface CortexClientOptions {
  baseUrl?: string;
  token?: string;
  timeout?: number;
}

export interface ServerInfo {
  name: string;
  version: string;
  did: string;
  endpoints: Record<string, string>;
  [key: string]: unknown;
}

export interface HealthCheck {
  status: string;
  timestamp: string;
  [key: string]: unknown;
}

export interface ContextNode {
  id: string;
  label: string;
  tags: string[];
  confidence: number;
  brief?: string;
  full_description?: string;
  properties?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ContextEdge {
  source: string;
  target: string;
  relation: string;
  weight?: number;
  [key: string]: unknown;
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  avg_degree: number;
  tag_distribution: Record<string, number>;
  [key: string]: unknown;
}

export interface PaginatedResponse<T> {
  items: T[];
  has_more: boolean;
  next_cursor?: string;
  total?: number;
}

export interface Grant {
  grant_id: string;
  audience: string;
  policy: string;
  scopes: string[];
  created_at: string;
  expires_at: string;
  revoked?: boolean;
  token?: string;
  [key: string]: unknown;
}

export interface CreateGrantOptions {
  audience: string;
  policy?: string;
  scopes?: string[];
  ttl_hours?: number;
}

export interface Webhook {
  webhook_id: string;
  url: string;
  events: string[];
  created_at: string;
  [key: string]: unknown;
}

export interface CreateWebhookOptions {
  url: string;
  events?: string[];
}

export interface Policy {
  name: string;
  include_tags?: string[];
  exclude_tags?: string[];
  min_confidence?: number;
  redact_properties?: string[];
  max_nodes?: number;
  builtin?: boolean;
  [key: string]: unknown;
}

export interface VersionSnapshot {
  version_id: string;
  timestamp: string;
  message: string;
  source: string;
  node_count: number;
  edge_count: number;
  parent_id?: string;
  signature?: string;
  [key: string]: unknown;
}

export interface VersionDiff {
  version_a: string;
  version_b: string;
  added_nodes: string[];
  removed_nodes: string[];
  modified_nodes: string[];
  added_edges: string[];
  removed_edges: string[];
  [key: string]: unknown;
}
