/**
 * Tests for CortexClient — uses node:test + node:http mock server.
 *
 * Spins up a real HTTP server with canned responses, exercises every
 * public method, and verifies error mapping.
 */

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import { CortexClient } from "../client.js";
import {
  CortexSDKError,
  AuthenticationError,
  ForbiddenError,
  NotFoundError,
  ValidationError,
  RateLimitError,
  ServerError,
} from "../errors.js";

// ---------------------------------------------------------------------------
// Mock CaaS server
// ---------------------------------------------------------------------------

const MOCK_PORT = 19876;

function mockServer(): http.Server {
  return http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", `http://localhost:${MOCK_PORT}`);
    const path = url.pathname;
    const method = req.method ?? "GET";

    // Collect request body
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      const respond = (
        status: number,
        body: unknown,
        contentType = "application/json",
      ) => {
        const payload =
          typeof body === "string" ? body : JSON.stringify(body);
        res.writeHead(status, { "Content-Type": contentType });
        res.end(payload);
      };

      // --- Discovery ---
      if (path === "/" && method === "GET") {
        return respond(200, {
          name: "cortex-caas",
          version: "1.0.0",
          did: "did:upai:ed25519:test",
          endpoints: { context: "/context" },
        });
      }
      if (path === "/.well-known/upai-configuration" && method === "GET") {
        return respond(200, {
          issuer: "did:upai:ed25519:test",
          context_endpoint: "/context",
        });
      }
      if (path === "/health" && method === "GET") {
        return respond(200, { status: "healthy", timestamp: "2026-01-01T00:00:00Z" });
      }
      if (path === "/identity" && method === "GET") {
        return respond(200, {
          id: "did:upai:ed25519:test",
          "@context": "https://www.w3.org/ns/did/v1",
        });
      }

      // --- Context ---
      if (path === "/context" && method === "GET") {
        return respond(200, {
          schema_version: "5.0",
          nodes: [{ id: "n1", label: "Python" }],
          edges: [],
        });
      }
      if (path === "/context/compact" && method === "GET") {
        return respond(200, "# Context\n- Python", "text/plain");
      }
      if (path === "/context/nodes" && method === "GET") {
        const cursor = url.searchParams.get("cursor");
        if (!cursor) {
          return respond(200, {
            items: [
              { id: "n1", label: "Python", tags: ["tech"], confidence: 0.9 },
              { id: "n2", label: "TypeScript", tags: ["tech"], confidence: 0.85 },
            ],
            has_more: true,
            next_cursor: "page2",
          });
        }
        return respond(200, {
          items: [
            { id: "n3", label: "Rust", tags: ["tech"], confidence: 0.7 },
          ],
          has_more: false,
        });
      }
      if (path === "/context/nodes/n1" && method === "GET") {
        return respond(200, {
          id: "n1",
          label: "Python",
          tags: ["tech"],
          confidence: 0.9,
        });
      }
      if (path === "/context/nodes/missing" && method === "GET") {
        return respond(404, { error: "Not found" });
      }
      if (path === "/context/edges" && method === "GET") {
        return respond(200, {
          items: [
            { source: "n1", target: "n2", relation: "related_to" },
          ],
          has_more: false,
        });
      }
      if (path === "/context/stats" && method === "GET") {
        return respond(200, {
          node_count: 3,
          edge_count: 1,
          avg_degree: 0.67,
          tag_distribution: { tech: 3 },
        });
      }

      // --- Versions ---
      if (path === "/versions" && method === "GET") {
        return respond(200, {
          items: [
            {
              version_id: "v1",
              timestamp: "2026-01-01T00:00:00Z",
              message: "init",
              source: "manual",
              node_count: 3,
              edge_count: 1,
            },
          ],
          has_more: false,
        });
      }
      if (path === "/versions/v1" && method === "GET") {
        return respond(200, {
          version_id: "v1",
          timestamp: "2026-01-01T00:00:00Z",
          message: "init",
          source: "manual",
          node_count: 3,
          edge_count: 1,
        });
      }
      if (path === "/versions/diff" && method === "GET") {
        return respond(200, {
          version_a: "v1",
          version_b: "v2",
          added_nodes: ["n4"],
          removed_nodes: [],
          modified_nodes: [],
          added_edges: [],
          removed_edges: [],
        });
      }

      // --- Grants ---
      if (path === "/grants" && method === "POST") {
        return respond(201, {
          grant_id: "g1",
          audience: "test",
          policy: "professional",
          scopes: ["context:read"],
          created_at: "2026-01-01T00:00:00Z",
          expires_at: "2026-01-02T00:00:00Z",
          token: "tok_test",
        });
      }
      if (path === "/grants" && method === "GET") {
        return respond(200, {
          grants: [
            {
              grant_id: "g1",
              audience: "test",
              policy: "professional",
              scopes: ["context:read"],
              created_at: "2026-01-01T00:00:00Z",
              expires_at: "2026-01-02T00:00:00Z",
            },
          ],
        });
      }
      if (path === "/grants/g1" && method === "DELETE") {
        return respond(200, { status: "revoked", grant_id: "g1" });
      }

      // --- Webhooks ---
      if (path === "/webhooks" && method === "POST") {
        return respond(201, {
          webhook_id: "w1",
          url: "https://example.com/hook",
          events: ["context.updated"],
          created_at: "2026-01-01T00:00:00Z",
        });
      }
      if (path === "/webhooks" && method === "GET") {
        return respond(200, {
          webhooks: [
            {
              webhook_id: "w1",
              url: "https://example.com/hook",
              events: ["context.updated"],
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
        });
      }
      if (path === "/webhooks/w1" && method === "DELETE") {
        return respond(200, { status: "deleted", webhook_id: "w1" });
      }

      // --- Policies ---
      if (path === "/policies" && method === "GET") {
        return respond(200, {
          policies: [
            { name: "full", builtin: true },
            { name: "professional", builtin: true },
          ],
        });
      }
      if (path === "/policies" && method === "POST") {
        return respond(201, {
          name: "custom",
          include_tags: ["tech"],
          min_confidence: 0.5,
        });
      }
      if (path === "/policies/full" && method === "GET") {
        return respond(200, { name: "full", builtin: true });
      }
      if (path === "/policies/custom" && method === "DELETE") {
        return respond(200, { status: "deleted", name: "custom" });
      }

      // --- Metrics ---
      if (path === "/metrics" && method === "GET") {
        return respond(
          200,
          "# HELP cortex_http_requests_total Total HTTP requests\ncortex_http_requests_total 42\n",
          "text/plain; version=0.0.4; charset=utf-8",
        );
      }

      // --- Error simulation ---
      if (path === "/error/401") {
        return respond(401, { error: "Unauthorized" });
      }
      if (path === "/error/403") {
        return respond(403, { error: "Forbidden" });
      }
      if (path === "/error/400") {
        return respond(400, { error: "Bad request" });
      }
      if (path === "/error/429") {
        return respond(429, { error: "Rate limited" });
      }
      if (path === "/error/500") {
        return respond(500, { error: "Internal server error" });
      }
      if (path === "/error/418") {
        return respond(418, { error: "I'm a teapot" });
      }

      respond(404, { error: "Not found" });
    });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CortexClient", () => {
  let server: http.Server;
  let client: CortexClient;

  before(async () => {
    server = mockServer();
    await new Promise<void>((resolve) =>
      server.listen(MOCK_PORT, "127.0.0.1", resolve),
    );
    client = new CortexClient({
      baseUrl: `http://127.0.0.1:${MOCK_PORT}`,
      token: "test-token",
    });
  });

  after(async () => {
    await new Promise<void>((resolve, reject) =>
      server.close((err) => (err ? reject(err) : resolve())),
    );
  });

  // --- Discovery ---

  it("info()", async () => {
    const info = await client.info();
    assert.equal(info.name, "cortex-caas");
    assert.equal(info.version, "1.0.0");
    assert.equal(info.did, "did:upai:ed25519:test");
  });

  it("discovery()", async () => {
    const disc = await client.discovery();
    assert.equal(disc.issuer, "did:upai:ed25519:test");
    assert.ok(disc.context_endpoint);
  });

  it("health()", async () => {
    const h = await client.health();
    assert.equal(h.status, "healthy");
    assert.ok(h.timestamp);
  });

  it("identity()", async () => {
    const id = await client.identity();
    assert.equal(id.id, "did:upai:ed25519:test");
  });

  // --- Context ---

  it("context()", async () => {
    const ctx = await client.context();
    assert.ok(Array.isArray(ctx.nodes));
  });

  it("contextCompact()", async () => {
    const md = await client.contextCompact();
    assert.equal(typeof md, "string");
    assert.ok(md.includes("Python"));
  });

  it("nodes() pagination via AsyncGenerator", async () => {
    const collected: unknown[] = [];
    for await (const node of client.nodes(2)) {
      collected.push(node);
    }
    assert.equal(collected.length, 3);
  });

  it("node() by ID", async () => {
    const n = await client.node("n1");
    assert.equal(n.id, "n1");
    assert.equal(n.label, "Python");
  });

  it("node() 404 throws NotFoundError", async () => {
    await assert.rejects(
      () => client.node("missing"),
      (err: unknown) => {
        assert.ok(err instanceof NotFoundError);
        assert.equal(err.statusCode, 404);
        return true;
      },
    );
  });

  it("edges()", async () => {
    const collected: unknown[] = [];
    for await (const edge of client.edges()) {
      collected.push(edge);
    }
    assert.equal(collected.length, 1);
  });

  it("stats()", async () => {
    const s = await client.stats();
    assert.equal(s.node_count, 3);
    assert.equal(s.edge_count, 1);
  });

  // --- Versions ---

  it("versions() pagination", async () => {
    const collected: unknown[] = [];
    for await (const v of client.versions()) {
      collected.push(v);
    }
    assert.ok(collected.length >= 1);
  });

  it("version() by ID", async () => {
    const v = await client.version("v1");
    assert.equal(v.version_id, "v1");
    assert.equal(v.message, "init");
  });

  it("versionDiff()", async () => {
    const diff = await client.versionDiff("v1", "v2");
    assert.equal(diff.version_a, "v1");
    assert.equal(diff.version_b, "v2");
    assert.ok(Array.isArray(diff.added_nodes));
  });

  // --- Grants ---

  it("createGrant()", async () => {
    const g = await client.createGrant({ audience: "test" });
    assert.equal(g.grant_id, "g1");
    assert.equal(g.audience, "test");
    assert.ok(g.token);
  });

  it("listGrants()", async () => {
    const grants = await client.listGrants();
    assert.ok(Array.isArray(grants));
    assert.equal(grants.length, 1);
    assert.equal(grants[0].grant_id, "g1");
  });

  it("revokeGrant()", async () => {
    const result = await client.revokeGrant("g1");
    assert.equal(result.status, "revoked");
  });

  // --- Webhooks ---

  it("createWebhook()", async () => {
    const w = await client.createWebhook({
      url: "https://example.com/hook",
      events: ["context.updated"],
    });
    assert.equal(w.webhook_id, "w1");
    assert.equal(w.url, "https://example.com/hook");
  });

  it("listWebhooks()", async () => {
    const wh = await client.listWebhooks();
    assert.ok(Array.isArray(wh));
    assert.equal(wh.length, 1);
  });

  it("deleteWebhook()", async () => {
    const result = await client.deleteWebhook("w1");
    assert.equal(result.status, "deleted");
  });

  // --- Policies ---

  it("listPolicies()", async () => {
    const policies = await client.listPolicies();
    assert.ok(Array.isArray(policies));
    assert.ok(policies.length >= 2);
  });

  it("createPolicy()", async () => {
    const p = await client.createPolicy("custom", {
      include_tags: ["tech"],
      min_confidence: 0.5,
    });
    assert.equal(p.name, "custom");
  });

  it("getPolicy()", async () => {
    const p = await client.getPolicy("full");
    assert.equal(p.name, "full");
  });

  it("deletePolicy()", async () => {
    const result = await client.deletePolicy("custom");
    assert.equal(result.status, "deleted");
  });

  // --- Metrics ---

  it("metrics() returns raw text", async () => {
    const m = await client.metrics();
    assert.equal(typeof m, "string");
    assert.ok(m.includes("cortex_http_requests_total"));
  });

  // --- Error mapping ---

  it("401 → AuthenticationError", async () => {
    const c = new CortexClient({
      baseUrl: `http://127.0.0.1:${MOCK_PORT}`,
    });
    await assert.rejects(
      () => (c as any)._request("GET", "/error/401"),
      (err: unknown) => {
        assert.ok(err instanceof AuthenticationError);
        assert.equal((err as AuthenticationError).statusCode, 401);
        return true;
      },
    );
  });

  it("403 → ForbiddenError", async () => {
    await assert.rejects(
      () => (client as any)._request("GET", "/error/403"),
      (err: unknown) => err instanceof ForbiddenError,
    );
  });

  it("400 → ValidationError", async () => {
    await assert.rejects(
      () => (client as any)._request("GET", "/error/400"),
      (err: unknown) => err instanceof ValidationError,
    );
  });

  it("429 → RateLimitError", async () => {
    await assert.rejects(
      () => (client as any)._request("GET", "/error/429"),
      (err: unknown) => err instanceof RateLimitError,
    );
  });

  it("500 → ServerError", async () => {
    await assert.rejects(
      () => (client as any)._request("GET", "/error/500"),
      (err: unknown) => err instanceof ServerError,
    );
  });

  it("418 → CortexSDKError (generic)", async () => {
    await assert.rejects(
      () => (client as any)._request("GET", "/error/418"),
      (err: unknown) => {
        assert.ok(err instanceof CortexSDKError);
        assert.ok(!(err instanceof ServerError));
        return true;
      },
    );
  });

  // --- Connection error ---

  it("connection error throws CortexSDKError", async () => {
    const badClient = new CortexClient({
      baseUrl: "http://127.0.0.1:1",
      timeout: 1000,
    });
    await assert.rejects(
      () => badClient.info(),
      (err: unknown) => {
        assert.ok(err instanceof CortexSDKError);
        return true;
      },
    );
  });

  // --- Timeout ---

  it("timeout throws CortexSDKError", async () => {
    // Create a server that never responds
    const slowServer = http.createServer(() => {
      // deliberately don't respond
    });
    await new Promise<void>((resolve) =>
      slowServer.listen(19877, "127.0.0.1", resolve),
    );

    const timeoutClient = new CortexClient({
      baseUrl: "http://127.0.0.1:19877",
      timeout: 100,
    });

    await assert.rejects(
      () => timeoutClient.info(),
      (err: unknown) => {
        assert.ok(err instanceof CortexSDKError);
        return true;
      },
    );

    await new Promise<void>((resolve, reject) =>
      slowServer.close((err) => (err ? reject(err) : resolve())),
    );
  });
});
