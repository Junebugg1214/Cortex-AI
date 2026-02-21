/**
 * CortexClient — TypeScript SDK for the CaaS API.
 *
 * Uses native fetch (no runtime dependencies). Maps HTTP errors to typed
 * exceptions. Supports async-generator pagination for list endpoints.
 */

import {
  CortexSDKError,
  AuthenticationError,
  ForbiddenError,
  NotFoundError,
  ValidationError,
  RateLimitError,
  ServerError,
} from "./errors.js";

import type {
  CortexClientOptions,
  ServerInfo,
  HealthCheck,
  ContextNode,
  ContextEdge,
  GraphStats,
  Grant,
  CreateGrantOptions,
  Webhook,
  CreateWebhookOptions,
  Policy,
  VersionSnapshot,
  VersionDiff,
} from "./types.js";

export class CortexClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly timeout: number;

  constructor(options: CortexClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8421").replace(
      /\/+$/,
      "",
    );
    this.token = options.token ?? "";
    this.timeout = options.timeout ?? 10_000;
  }

  // -----------------------------------------------------------------
  // Discovery (no auth)
  // -----------------------------------------------------------------

  /** GET / — server info. */
  async info(): Promise<ServerInfo> {
    return (await this._request("GET", "/", { auth: false })) as ServerInfo;
  }

  /** GET /.well-known/upai-configuration — UPAI discovery. */
  async discovery(): Promise<Record<string, unknown>> {
    return this._request("GET", "/.well-known/upai-configuration", {
      auth: false,
    });
  }

  /** GET /health — health check (no auth). */
  async health(): Promise<HealthCheck> {
    return (await this._request("GET", "/health", {
      auth: false,
    })) as HealthCheck;
  }

  /** GET /identity — W3C DID Document. */
  async identity(): Promise<Record<string, unknown>> {
    return this._request("GET", "/identity", { auth: false });
  }

  // -----------------------------------------------------------------
  // Context
  // -----------------------------------------------------------------

  /** GET /context — full signed graph (filtered by token policy). */
  async context(): Promise<Record<string, unknown>> {
    return this._request("GET", "/context");
  }

  /** GET /context/compact — markdown summary (raw string). */
  async contextCompact(): Promise<string> {
    return this._request("GET", "/context/compact", { raw: true });
  }

  /** Auto-paginating async generator over /context/nodes. */
  async *nodes(limit = 20): AsyncGenerator<ContextNode> {
    yield* this._paginate<ContextNode>("/context/nodes", limit);
  }

  /** GET /context/nodes/:id — single node. */
  async node(nodeId: string): Promise<ContextNode> {
    return (await this._request("GET", `/context/nodes/${nodeId}`)) as ContextNode;
  }

  /** Auto-paginating async generator over /context/edges. */
  async *edges(limit = 20): AsyncGenerator<ContextEdge> {
    yield* this._paginate<ContextEdge>("/context/edges", limit);
  }

  /** GET /context/stats — graph statistics. */
  async stats(): Promise<GraphStats> {
    return (await this._request("GET", "/context/stats")) as GraphStats;
  }

  // -----------------------------------------------------------------
  // Versions
  // -----------------------------------------------------------------

  /** Auto-paginating async generator over /versions. */
  async *versions(limit = 20): AsyncGenerator<VersionSnapshot> {
    yield* this._paginate<VersionSnapshot>("/versions", limit);
  }

  /** GET /versions/:id — single version snapshot. */
  async version(versionId: string): Promise<VersionSnapshot> {
    return (await this._request("GET", `/versions/${versionId}`)) as VersionSnapshot;
  }

  /** GET /versions/diff?a=...&b=... — diff two versions. */
  async versionDiff(a: string, b: string): Promise<VersionDiff> {
    return (await this._request("GET", `/versions/diff?a=${a}&b=${b}`)) as VersionDiff;
  }

  // -----------------------------------------------------------------
  // Grants
  // -----------------------------------------------------------------

  /** POST /grants — create a new grant token. */
  async createGrant(options: CreateGrantOptions): Promise<Grant> {
    const body: Record<string, unknown> = {
      audience: options.audience,
      policy: options.policy ?? "professional",
      ttl_hours: options.ttl_hours ?? 24,
    };
    if (options.scopes) {
      body.scopes = options.scopes;
    }
    return (await this._request("POST", "/grants", { body })) as Grant;
  }

  /** GET /grants — list all grants. */
  async listGrants(): Promise<Grant[]> {
    const data = await this._request("GET", "/grants");
    return (data.grants ?? []) as Grant[];
  }

  /** DELETE /grants/:id — revoke a grant. */
  async revokeGrant(grantId: string): Promise<Record<string, unknown>> {
    return this._request("DELETE", `/grants/${grantId}`);
  }

  // -----------------------------------------------------------------
  // Webhooks
  // -----------------------------------------------------------------

  /** POST /webhooks — register a webhook. */
  async createWebhook(options: CreateWebhookOptions): Promise<Webhook> {
    const body: Record<string, unknown> = { url: options.url };
    if (options.events) {
      body.events = options.events;
    }
    return (await this._request("POST", "/webhooks", { body })) as Webhook;
  }

  /** GET /webhooks — list all webhooks. */
  async listWebhooks(): Promise<Webhook[]> {
    const data = await this._request("GET", "/webhooks");
    return (data.webhooks ?? []) as Webhook[];
  }

  /** DELETE /webhooks/:id — delete a webhook. */
  async deleteWebhook(webhookId: string): Promise<Record<string, unknown>> {
    return this._request("DELETE", `/webhooks/${webhookId}`);
  }

  // -----------------------------------------------------------------
  // Policies
  // -----------------------------------------------------------------

  /** GET /policies — list all disclosure policies. */
  async listPolicies(): Promise<Policy[]> {
    const data = await this._request("GET", "/policies");
    return (data.policies ?? []) as Policy[];
  }

  /** POST /policies — create a custom policy. */
  async createPolicy(
    name: string,
    options: Partial<Policy> = {},
  ): Promise<Policy> {
    return (await this._request("POST", "/policies", {
      body: { name, ...options },
    })) as Policy;
  }

  /** GET /policies/:name — get a single policy. */
  async getPolicy(name: string): Promise<Policy> {
    return (await this._request("GET", `/policies/${name}`)) as Policy;
  }

  /** DELETE /policies/:name — delete a custom policy. */
  async deletePolicy(name: string): Promise<Record<string, unknown>> {
    return this._request("DELETE", `/policies/${name}`);
  }

  // -----------------------------------------------------------------
  // Metrics
  // -----------------------------------------------------------------

  /** GET /metrics — Prometheus text exposition (raw string). */
  async metrics(): Promise<string> {
    return this._request("GET", "/metrics", { auth: false, raw: true });
  }

  // -----------------------------------------------------------------
  // Internals
  // -----------------------------------------------------------------

  private async _request(
    method: string,
    path: string,
    options: { body?: Record<string, unknown>; auth?: boolean; raw: true },
  ): Promise<string>;
  private async _request(
    method: string,
    path: string,
    options?: { body?: Record<string, unknown>; auth?: boolean; raw?: false },
  ): Promise<Record<string, unknown>>;
  private async _request(
    method: string,
    path: string,
    options: {
      body?: Record<string, unknown>;
      auth?: boolean;
      raw?: boolean;
    } = {},
  ): Promise<Record<string, unknown> | string> {
    const { body, auth = true, raw = false } = options;
    const url = this.baseUrl + path;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (auth && this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err: unknown) {
      clearTimeout(timer);
      if (err instanceof Error && err.name === "AbortError") {
        throw new CortexSDKError(`Request timeout after ${this.timeout}ms`);
      }
      const msg =
        err instanceof Error ? err.message : "Unknown connection error";
      throw new CortexSDKError(`Connection error: ${msg}`);
    } finally {
      clearTimeout(timer);
    }

    if (response.ok) {
      if (raw) {
        return response.text();
      }
      return response.json() as Promise<Record<string, unknown>>;
    }

    // Error path — map HTTP status to typed exception
    let errBody: Record<string, unknown> = {};
    try {
      errBody = (await response.json()) as Record<string, unknown>;
    } catch {
      // response may not be JSON
    }

    let msg: string;
    const errField = errBody.error;
    if (typeof errField === "object" && errField !== null && "message" in errField) {
      msg = String((errField as Record<string, unknown>).message);
    } else if (typeof errField === "string") {
      msg = errField;
    } else {
      msg = String(response.status);
    }

    const status = response.status;
    switch (status) {
      case 401:
        throw new AuthenticationError(msg, status, errBody);
      case 403:
        throw new ForbiddenError(msg, status, errBody);
      case 404:
        throw new NotFoundError(msg, status, errBody);
      case 400:
        throw new ValidationError(msg, status, errBody);
      case 429:
        throw new RateLimitError(msg, status, errBody);
      default:
        if (status >= 500) {
          throw new ServerError(msg, status, errBody);
        }
        throw new CortexSDKError(msg, status, errBody);
    }
  }

  private async *_paginate<T>(
    path: string,
    limit: number,
  ): AsyncGenerator<T> {
    let cursor: string | undefined;
    while (true) {
      let qs = `?limit=${limit}`;
      if (cursor) {
        qs += `&cursor=${cursor}`;
      }
      const data = await this._request("GET", path + qs);
      const items = (data.items ?? []) as T[];
      for (const item of items) {
        yield item;
      }
      if (!data.has_more) {
        break;
      }
      cursor = data.next_cursor as string | undefined;
      if (!cursor) {
        break;
      }
    }
  }
}
