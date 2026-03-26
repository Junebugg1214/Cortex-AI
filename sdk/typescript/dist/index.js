function buildQuery(params) {
  const pairs = Object.entries(params ?? {}).filter(([, value]) => value !== undefined && value !== null);
  if (!pairs.length) {
    return "";
  }
  return `?${new URLSearchParams(pairs.map(([key, value]) => [key, String(value)])).toString()}`;
}

async function parseResponse(response) {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.error ?? response.statusText);
  }
  return payload;
}

export class CortexClient {
  constructor(baseUrl, options = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey ?? null;
    this.timeoutMs = options.timeoutMs ?? 30000;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
    if (!this.fetchImpl) {
      throw new Error("A global fetch implementation is required.");
    }
  }

  headers() {
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json"
    };
    if (this.apiKey) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }
    return headers;
  }

  async request(method, path, { params, payload } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}${buildQuery(params)}`, {
        method,
        headers: this.headers(),
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: controller.signal
      });
      return await parseResponse(response);
    } finally {
      clearTimeout(timeout);
    }
  }

  health() {
    return this.request("GET", "/v1/health");
  }

  meta() {
    return this.request("GET", "/v1/meta");
  }

  openapi() {
    return this.request("GET", "/v1/openapi.json");
  }

  log({ limit = 10, ref } = {}) {
    return this.request("GET", "/v1/commits", { params: { limit, ref } });
  }

  listBranches() {
    return this.request("GET", "/v1/branches");
  }

  createBranch({ name, fromRef = "HEAD", switchBranch = false, actor = "manual", approve = false }) {
    return this.request("POST", "/v1/branches", {
      payload: { name, from_ref: fromRef, switch: switchBranch, actor, approve }
    });
  }

  switchBranch({ name, actor = "manual", approve = false }) {
    return this.request("POST", "/v1/branches/switch", {
      payload: { name, actor, approve }
    });
  }

  checkout({ ref = "HEAD", verify = true } = {}) {
    return this.request("POST", "/v1/checkout", { payload: { ref, verify } });
  }

  diff({ versionA, versionB }) {
    return this.request("POST", "/v1/diff", {
      payload: { version_a: versionA, version_b: versionB }
    });
  }

  commit({ graph, message, source = "manual", actor = "manual", approve = false }) {
    return this.request("POST", "/v1/commit", {
      payload: { graph, message, source, actor, approve }
    });
  }

  review({ against, graph, ref = "HEAD", failOn = "blocking" }) {
    return this.request("POST", "/v1/review", {
      payload: { against, graph, ref, fail_on: failOn }
    });
  }

  blame({ label = "", nodeId = "", graph, ref = "HEAD", source = "", limit = 20 } = {}) {
    return this.request("POST", "/v1/blame", {
      payload: { label, node_id: nodeId, graph, ref, source, limit }
    });
  }

  history({ label = "", nodeId = "", graph, ref = "HEAD", source = "", limit = 20 } = {}) {
    return this.request("POST", "/v1/history", {
      payload: { label, node_id: nodeId, graph, ref, source, limit }
    });
  }

  detectConflicts({ graph, ref = "HEAD", minSeverity = 0.0 } = {}) {
    return this.request("POST", "/v1/conflicts/detect", {
      payload: { graph, ref, min_severity: minSeverity }
    });
  }

  resolveConflict({ conflictId, action, graph, ref = "HEAD" }) {
    return this.request("POST", "/v1/conflicts/resolve", {
      payload: { conflict_id: conflictId, action, graph, ref }
    });
  }

  mergePreview({ otherRef, currentRef = "HEAD", persist = false }) {
    return this.request("POST", "/v1/merge-preview", {
      payload: { other_ref: otherRef, current_ref: currentRef, persist }
    });
  }

  mergeConflicts() {
    return this.request("POST", "/v1/merge/conflicts", { payload: {} });
  }

  mergeResolve({ conflictId, choose }) {
    return this.request("POST", "/v1/merge/resolve", {
      payload: { conflict_id: conflictId, choose }
    });
  }

  mergeCommitResolved({ message, actor = "manual", approve = false } = {}) {
    return this.request("POST", "/v1/merge/commit-resolved", {
      payload: { message, actor, approve }
    });
  }

  mergeAbort() {
    return this.request("POST", "/v1/merge/abort", { payload: {} });
  }

  queryCategory({ tag, graph, ref = "HEAD" }) {
    return this.request("POST", "/v1/query/category", {
      payload: { tag, graph, ref }
    });
  }

  queryPath({ fromLabel, toLabel, graph, ref = "HEAD" }) {
    return this.request("POST", "/v1/query/path", {
      payload: { from_label: fromLabel, to_label: toLabel, graph, ref }
    });
  }

  queryRelated({ label, depth = 2, graph, ref = "HEAD" }) {
    return this.request("POST", "/v1/query/related", {
      payload: { label, depth, graph, ref }
    });
  }

  querySearch({ query, graph, ref = "HEAD", limit = 10, minScore = 0.0 }) {
    return this.request("POST", "/v1/query/search", {
      payload: { query, graph, ref, limit, min_score: minScore }
    });
  }

  queryDsl({ query, graph, ref = "HEAD" }) {
    return this.request("POST", "/v1/query/dsl", {
      payload: { query, graph, ref }
    });
  }

  queryNl({ query, graph, ref = "HEAD" }) {
    return this.request("POST", "/v1/query/nl", {
      payload: { query, graph, ref }
    });
  }
}
