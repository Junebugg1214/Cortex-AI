export const SDK_NAME = "@cortex-ai/sdk";
export const SDK_VERSION = "1.4.1";
export const API_VERSION = "v1";
export const OPENAPI_VERSION = "1.0.0";

function slugFragment(value, fallback = "task") {
  const slug = String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || fallback;
}

function truncateText(text, maxChars) {
  if (maxChars == null || text.length <= maxChars) {
    return text;
  }
  if (maxChars <= 3) {
    return text.slice(0, maxChars);
  }
  return `${text.slice(0, maxChars - 3).replace(/\s+$/g, "")}...`;
}

function nodeSummary(node) {
  const parts = [];
  const summary =
    String(node.brief ?? "").trim() ||
    String(node.full_description ?? "").trim() ||
    String(node.description ?? "").trim();
  if (summary) {
    parts.push(summary);
  }
  const tags = Array.isArray(node.tags) ? node.tags.map(String).filter(Boolean) : [];
  if (tags.length) {
    parts.push(`tags: ${tags.slice(0, 4).join(", ")}`);
  }
  const aliases = Array.isArray(node.aliases) ? node.aliases.map(String).filter(Boolean) : [];
  if (aliases.length) {
    parts.push(`aliases: ${aliases.slice(0, 3).join(", ")}`);
  }
  return parts.join("; ");
}

export function branchNameForTask(task, { prefix = "tasks", maxLength = 48 } = {}) {
  const branchLeaf = slugFragment(task).slice(0, maxLength).replace(/-+$/g, "") || "task";
  const prefixParts = String(prefix ?? "")
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => slugFragment(part));
  return prefixParts.length ? `${prefixParts.join("/")}/${branchLeaf}` : branchLeaf;
}

export function renderSearchContext(
  searchPayload,
  { maxItems = 5, maxChars = 1500, includeScores = true } = {}
) {
  const query = String(searchPayload?.query ?? "").trim();
  const results = Array.isArray(searchPayload?.results) ? searchPayload.results.slice(0, maxItems) : [];
  if (!results.length) {
    return query ? `No Cortex memory matched '${query}'.` : "No Cortex memory matched.";
  }
  const header = query ? `Cortex memory matches for '${query}':` : "Cortex memory matches:";
  const lines = [header];
  for (const item of results) {
    const node = item?.node ?? {};
    const label = String(node.label ?? node.id ?? "Untitled memory").trim();
    let line = `- ${label}`;
    if (includeScores && typeof item?.score === "number") {
      line += ` (score ${item.score.toFixed(3)})`;
    }
    const summary = nodeSummary(node);
    if (summary) {
      line += `: ${summary}`;
    }
    lines.push(line);
  }
  return truncateText(lines.join("\n"), maxChars);
}

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
    this.namespace = options.namespace ?? null;
    this.timeoutMs = options.timeoutMs ?? 30000;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
    if (!this.fetchImpl) {
      throw new Error("A global fetch implementation is required.");
    }
  }

  headers() {
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Cortex-Client": `${SDK_NAME}/${SDK_VERSION}`
    };
    if (this.apiKey) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }
    if (this.namespace) {
      headers["X-Cortex-Namespace"] = this.namespace;
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

  sdkInfo() {
    return {
      name: SDK_NAME,
      version: SDK_VERSION,
      apiVersion: API_VERSION,
      openapiVersion: OPENAPI_VERSION
    };
  }

  meta() {
    return this.request("GET", "/v1/meta");
  }

  metrics() {
    return this.request("GET", "/v1/metrics");
  }

  openapi() {
    return this.request("GET", "/v1/openapi.json");
  }

  indexStatus({ ref = "HEAD" } = {}) {
    return this.request("GET", "/v1/index/status", { params: { ref } });
  }

  indexRebuild({ ref = "HEAD", allRefs = false } = {}) {
    return this.request("POST", "/v1/index/rebuild", {
      payload: { ref, all_refs: allRefs }
    });
  }

  pruneStatus({ retentionDays = 7 } = {}) {
    return this.request("GET", "/v1/prune/status", {
      params: { retention_days: retentionDays }
    });
  }

  prune({ dryRun = true, retentionDays = 7 } = {}) {
    return this.request("POST", "/v1/prune", {
      payload: { dry_run: dryRun, retention_days: retentionDays }
    });
  }

  pruneAudit({ limit = 50 } = {}) {
    return this.request("GET", "/v1/prune/audit", {
      params: { limit }
    });
  }

  lookupNodes({ nodeId = "", canonicalId = "", label = "", ref = "HEAD", limit = 10 } = {}) {
    return this.request("GET", "/v1/nodes", {
      params: { id: nodeId, canonical_id: canonicalId, label, ref, limit }
    });
  }

  getNode({ nodeId, ref = "HEAD" }) {
    return this.request("GET", `/v1/nodes/${encodeURIComponent(nodeId)}`, {
      params: { ref }
    });
  }

  upsertNode({
    node,
    ref = "HEAD",
    message = "",
    source = "api.object",
    actor = "manual",
    approve = false,
    recordClaim = true,
    claimSource = "",
    claimMethod = "nodes.upsert",
    claimMetadata
  }) {
    return this.request("POST", "/v1/nodes/upsert", {
      payload: {
        node,
        ref,
        message,
        source,
        actor,
        approve,
        record_claim: recordClaim,
        claim_source: claimSource,
        claim_method: claimMethod,
        claim_metadata: claimMetadata
      }
    });
  }

  deleteNode({
    nodeId = "",
    canonicalId = "",
    label = "",
    ref = "HEAD",
    message = "",
    source = "api.object",
    actor = "manual",
    approve = false,
    recordClaim = true,
    claimSource = "",
    claimMethod = "nodes.delete",
    claimMetadata
  } = {}) {
    return this.request("POST", "/v1/nodes/delete", {
      payload: {
        node_id: nodeId,
        canonical_id: canonicalId,
        label,
        ref,
        message,
        source,
        actor,
        approve,
        record_claim: recordClaim,
        claim_source: claimSource,
        claim_method: claimMethod,
        claim_metadata: claimMetadata
      }
    });
  }

  lookupEdges({ edgeId = "", sourceId = "", targetId = "", relation = "", ref = "HEAD", limit = 10 } = {}) {
    return this.request("GET", "/v1/edges", {
      params: { id: edgeId, source_id: sourceId, target_id: targetId, relation, ref, limit }
    });
  }

  getEdge({ edgeId, ref = "HEAD" }) {
    return this.request("GET", `/v1/edges/${encodeURIComponent(edgeId)}`, {
      params: { ref }
    });
  }

  upsertEdge({ edge, ref = "HEAD", message = "", source = "api.object", actor = "manual", approve = false }) {
    return this.request("POST", "/v1/edges/upsert", {
      payload: { edge, ref, message, source, actor, approve }
    });
  }

  deleteEdge({
    edgeId = "",
    sourceId = "",
    targetId = "",
    relation = "",
    ref = "HEAD",
    message = "",
    source = "api.object",
    actor = "manual",
    approve = false
  } = {}) {
    return this.request("POST", "/v1/edges/delete", {
      payload: {
        edge_id: edgeId,
        source_id: sourceId,
        target_id: targetId,
        relation,
        ref,
        message,
        source,
        actor,
        approve
      }
    });
  }

  listClaims({
    claimId = "",
    nodeId = "",
    canonicalId = "",
    label = "",
    source = "",
    ref = "",
    versionRef = "",
    op = "",
    limit = 50
  } = {}) {
    return this.request("GET", "/v1/claims", {
      params: {
        claim_id: claimId,
        node_id: nodeId,
        canonical_id: canonicalId,
        label,
        source,
        ref,
        version_ref: versionRef,
        op,
        limit
      }
    });
  }

  assertClaim({
    node,
    nodeId = "",
    canonicalId = "",
    label = "",
    ref = "HEAD",
    materialize = true,
    message = "",
    source = "api.object",
    method = "claims.assert",
    actor = "manual",
    approve = false,
    metadata
  } = {}) {
    return this.request("POST", "/v1/claims/assert", {
      payload: {
        node,
        node_id: nodeId,
        canonical_id: canonicalId,
        label,
        ref,
        materialize,
        message,
        source,
        method,
        actor,
        approve,
        metadata
      }
    });
  }

  retractClaim({
    claimId = "",
    nodeId = "",
    canonicalId = "",
    label = "",
    ref = "HEAD",
    materialize = true,
    message = "",
    actor = "manual",
    approve = false,
    metadata
  } = {}) {
    return this.request("POST", "/v1/claims/retract", {
      payload: {
        claim_id: claimId,
        node_id: nodeId,
        canonical_id: canonicalId,
        label,
        ref,
        materialize,
        message,
        actor,
        approve,
        metadata
      }
    });
  }

  memoryBatch({ operations, ref = "HEAD", message = "", source = "api.object", actor = "manual", approve = false }) {
    return this.request("POST", "/v1/memory/batch", {
      payload: { operations, ref, message, source, actor, approve }
    });
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

export class MemorySession {
  constructor(client, options = {}) {
    this.client = client;
    this.actor = options.actor ?? "assistant";
    this.defaultRef = options.defaultRef ?? "HEAD";
    this.branchPrefix = options.branchPrefix ?? "tasks";
    this.defaultSource = options.defaultSource ?? "sdk.session";
    this.defaultFailOn = options.defaultFailOn ?? "blocking";
  }

  static fromBaseUrl(baseUrl, { clientOptions = {}, sessionOptions = {} } = {}) {
    return new MemorySession(new CortexClient(baseUrl, clientOptions), sessionOptions);
  }

  sdkInfo() {
    return {
      ...this.client.sdkInfo(),
      session: {
        actor: this.actor,
        defaultRef: this.defaultRef,
        branchPrefix: this.branchPrefix,
        defaultSource: this.defaultSource,
        defaultFailOn: this.defaultFailOn
      }
    };
  }

  remember({
    label = "",
    node,
    nodeId = "",
    canonicalId = "",
    brief = "",
    fullDescription = "",
    tags = [],
    aliases = [],
    confidence = 0.85,
    status = "",
    validFrom = "",
    validTo = "",
    properties,
    message = "",
    ref = this.defaultRef,
    source = `${this.defaultSource}.remember`,
    approve = false,
    claimMetadata
  } = {}) {
    let nodePayload = { ...(node ?? {}) };
    if (!Object.keys(nodePayload).length) {
      if (!label) {
        throw new Error("remember() needs either a node payload or a non-empty label.");
      }
      nodePayload = { label, confidence };
      if (nodeId) {
        nodePayload.id = nodeId;
      }
      if (canonicalId) {
        nodePayload.canonical_id = canonicalId;
      }
      if (brief) {
        nodePayload.brief = brief;
      }
      if (fullDescription) {
        nodePayload.full_description = fullDescription;
      }
      if (status) {
        nodePayload.status = status;
      }
      if (validFrom) {
        nodePayload.valid_from = validFrom;
      }
      if (validTo) {
        nodePayload.valid_to = validTo;
      }
      if (tags.length) {
        nodePayload.tags = tags;
      }
      if (aliases.length) {
        nodePayload.aliases = aliases;
      }
    }
    if (properties) {
      nodePayload = { ...nodePayload, ...properties };
    }
    return this.client.upsertNode({
      node: nodePayload,
      ref,
      message: message || `Remember ${nodePayload.label ?? nodePayload.id ?? "memory"}`,
      source,
      actor: this.actor,
      approve,
      claimMetadata
    });
  }

  rememberMany({ nodes, message = "", ref = this.defaultRef, source = `${this.defaultSource}.remember_many`, approve = false }) {
    const operations = (nodes ?? []).map((node) => ({ op: "upsert_node", node: { ...node } }));
    return this.client.memoryBatch({
      operations,
      ref,
      message: message || `Remember ${operations.length} memory object(s)`,
      source,
      actor: this.actor,
      approve
    });
  }

  link({
    sourceId,
    targetId,
    relation,
    edge,
    edgeId = "",
    confidence = 0.8,
    description = "",
    message = "",
    ref = this.defaultRef,
    source = `${this.defaultSource}.link`,
    approve = false
  }) {
    let edgePayload = { ...(edge ?? {}) };
    if (!Object.keys(edgePayload).length) {
      edgePayload = {
        source_id: sourceId,
        target_id: targetId,
        relation,
        confidence
      };
      if (edgeId) {
        edgePayload.id = edgeId;
      }
      if (description) {
        edgePayload.description = description;
      }
    }
    return this.client.upsertEdge({
      edge: edgePayload,
      ref,
      message: message || `Link ${sourceId} -> ${targetId} (${relation})`,
      source,
      actor: this.actor,
      approve
    });
  }

  search({ query, ref = this.defaultRef, limit = 5, minScore = 0.0 }) {
    return this.client.querySearch({ query, ref, limit, minScore });
  }

  async searchContext({
    query,
    ref = this.defaultRef,
    limit = 5,
    minScore = 0.0,
    maxChars = 1500,
    includeScores = true
  }) {
    const payload = await this.search({ query, ref, limit, minScore });
    return {
      ...payload,
      context: renderSearchContext(payload, { maxItems: limit, maxChars, includeScores })
    };
  }

  branchForTask({ task, prefix = this.branchPrefix, fromRef = this.defaultRef, switchBranch = true, approve = false }) {
    const branchName = branchNameForTask(task, { prefix });
    return this.client.createBranch({
      name: branchName,
      fromRef,
      switchBranch,
      actor: this.actor,
      approve
    }).then((payload) => ({
      ...payload,
      branch_name: branchName,
      task
    }));
  }

  async commitIfReviewPasses({
    graph,
    message,
    against,
    ref = this.defaultRef,
    failOn = this.defaultFailOn,
    source = `${this.defaultSource}.commit_if_review_passes`,
    approve = false
  }) {
    const review = await this.client.review({ against, graph, ref, failOn });
    if (review.status === "fail") {
      const summary = review.summary ?? {};
      const failureCounts = review.failure_counts ?? {};
      const renderedCounts = Object.entries(failureCounts)
        .filter(([, value]) => value)
        .map(([key, value]) => `${key}=${value}`)
        .join(", ");
      const details = [
        summary.blocking_issues != null ? `blocking=${summary.blocking_issues}` : "",
        renderedCounts
      ]
        .filter(Boolean)
        .join(", ");
      throw new Error(`Review failed before commit: ${details || "blocking review policy triggered"}`);
    }
    const commit = await this.client.commit({
      graph,
      message,
      source,
      actor: this.actor,
      approve
    });
    return {
      status: "ok",
      review,
      commit: commit.commit ?? commit
    };
  }
}
