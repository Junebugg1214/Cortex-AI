"""
Small local web UI for Git-for-AI-Memory workflows.

Zero-dependency HTTP server with a single-page interface for review, blame,
history, governance, and remote sync operations.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cortex.claims import ClaimLedger
from cortex.cli import _load_graph
from cortex.governance import GOVERNANCE_ACTIONS, GovernanceRule, GovernanceStore
from cortex.memory_ops import blame_memory_nodes
from cortex.remotes import MemoryRemote, RemoteRegistry, fork_remote, pull_remote, push_remote
from cortex.review import parse_failure_policies, review_graphs
from cortex.upai.versioning import VersionStore


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


class MemoryUIBackend:
    def __init__(self, store_dir: str | Path, context_file: str | Path | None = None) -> None:
        self.store_dir = Path(store_dir)
        self.context_file = Path(context_file).resolve() if context_file else None

    def _default_context_file(self) -> Path | None:
        if self.context_file:
            return self.context_file
        candidate = Path.cwd() / "context.json"
        return candidate if candidate.exists() else None

    def _resolve_input_file(self, provided: str | None) -> Path:
        if provided:
            path = Path(provided).expanduser().resolve()
        else:
            default = self._default_context_file()
            if default is None:
                raise ValueError("No context file provided and no default context.json found.")
            path = default
        if not path.exists():
            raise ValueError(f"Context file not found: {path}")
        return path

    def meta(self) -> dict[str, Any]:
        store = VersionStore(self.store_dir)
        current = store.current_branch()
        return {
            "store_dir": str(self.store_dir.resolve()),
            "context_file": str(self._default_context_file()) if self._default_context_file() else "",
            "current_branch": current,
            "head": store.resolve_ref("HEAD"),
        }

    def review(self, *, input_file: str | None, against: str, ref: str = "HEAD", fail_on: str = "blocking") -> dict[str, Any]:
        store = VersionStore(self.store_dir)
        against_version = store.resolve_ref(against)
        if against_version is None:
            raise ValueError(f"Unknown baseline ref: {against}")
        against_graph = store.checkout(against_version)

        if input_file:
            input_path = self._resolve_input_file(input_file)
            current_graph = _load_graph(input_path)
            current_label = str(input_path)
        else:
            current_version = store.resolve_ref(ref)
            if current_version is None:
                raise ValueError(f"Unknown current ref: {ref}")
            current_graph = store.checkout(current_version)
            current_label = current_version

        fail_policies = parse_failure_policies(fail_on)
        review = review_graphs(current_graph, against_graph, current_label=current_label, against_label=against_version)
        result = review.to_dict()
        should_fail, failure_counts = review.should_fail(fail_policies)
        result["status"] = "fail" if should_fail else "pass"
        result["fail_on"] = fail_policies
        result["failure_counts"] = failure_counts
        return result

    def blame(
        self,
        *,
        input_file: str | None,
        label: str = "",
        node_id: str = "",
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        input_path = self._resolve_input_file(input_file)
        graph = _load_graph(input_path)
        store = VersionStore(self.store_dir) if (self.store_dir / "history.json").exists() else None
        ledger = ClaimLedger(self.store_dir) if (self.store_dir / "claims.jsonl").exists() else None
        return blame_memory_nodes(
            graph,
            label=label or None,
            node_id=node_id or None,
            store=store,
            ledger=ledger,
            ref=ref,
            source=source,
            version_limit=limit,
        )

    def history(
        self,
        *,
        input_file: str | None,
        label: str = "",
        node_id: str = "",
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "ref": ref,
            "source": source,
            "nodes": self.blame(
                input_file=input_file,
                label=label,
                node_id=node_id,
                ref=ref,
                source=source,
                limit=limit,
            )["nodes"],
        }

    def list_governance_rules(self) -> dict[str, Any]:
        governance = GovernanceStore(self.store_dir)
        return {"rules": [rule.to_dict() for rule in governance.list_rules()]}

    def save_governance_rule(self, *, effect: str, payload: dict[str, Any]) -> dict[str, Any]:
        actions = list(payload.get("actions") or payload.get("action") or [])
        namespaces = list(payload.get("namespaces") or payload.get("namespace") or [])
        invalid = [item for item in actions if item != "*" and item not in GOVERNANCE_ACTIONS]
        if invalid:
            raise ValueError(f"Unknown governance action(s): {', '.join(sorted(invalid))}")
        rule = GovernanceRule(
            name=payload["name"],
            effect=effect,
            actor_pattern=payload.get("actor_pattern", "*"),
            actions=actions or ["*"],
            namespaces=namespaces or ["*"],
            require_approval=bool(payload.get("require_approval", False)),
            approval_below_confidence=payload.get("approval_below_confidence"),
            approval_tags=list(payload.get("approval_tags", [])),
            approval_change_types=list(payload.get("approval_change_types", [])),
            description=payload.get("description", ""),
        )
        governance = GovernanceStore(self.store_dir)
        governance.upsert_rule(rule)
        return {"status": "ok", "rule": rule.to_dict()}

    def delete_governance_rule(self, name: str) -> dict[str, Any]:
        governance = GovernanceStore(self.store_dir)
        removed = governance.remove_rule(name)
        return {"status": "ok" if removed else "missing", "name": name}

    def check_governance(
        self,
        *,
        actor: str,
        action: str,
        namespace: str,
        input_file: str | None = None,
        against: str | None = None,
    ) -> dict[str, Any]:
        current_graph = _load_graph(self._resolve_input_file(input_file)) if input_file else None
        baseline_graph = None
        if against:
            store = VersionStore(self.store_dir)
            version_id = store.resolve_ref(against)
            if version_id is None:
                raise ValueError(f"Unknown baseline ref: {against}")
            baseline_graph = store.checkout(version_id)
        governance = GovernanceStore(self.store_dir)
        return governance.authorize(
            actor,
            action,
            namespace,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        ).to_dict()

    def list_remotes(self) -> dict[str, Any]:
        registry = RemoteRegistry(self.store_dir)
        return {
            "remotes": [
                remote.to_dict() | {"store_path": str(remote.store_path)}
                for remote in registry.list_remotes()
            ]
        }

    def add_remote(self, *, name: str, path: str, default_branch: str = "main") -> dict[str, Any]:
        remote = MemoryRemote(name=name, path=path, default_branch=default_branch)
        registry = RemoteRegistry(self.store_dir)
        registry.add(remote)
        return {"status": "ok", "remote": remote.to_dict() | {"store_path": str(remote.store_path)}}

    def remove_remote(self, name: str) -> dict[str, Any]:
        registry = RemoteRegistry(self.store_dir)
        removed = registry.remove(name)
        return {"status": "ok" if removed else "missing", "name": name}

    def remote_push(self, *, name: str, branch: str = "HEAD", to_branch: str | None = None, force: bool = False) -> dict[str, Any]:
        registry = RemoteRegistry(self.store_dir)
        remote = registry.get(name)
        if remote is None:
            raise ValueError(f"Unknown remote: {name}")
        return push_remote(VersionStore(self.store_dir), remote, branch=branch, target_branch=to_branch, force=force)

    def remote_pull(
        self,
        *,
        name: str,
        branch: str | None = None,
        into_branch: str | None = None,
        switch: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        registry = RemoteRegistry(self.store_dir)
        remote = registry.get(name)
        if remote is None:
            raise ValueError(f"Unknown remote: {name}")
        return pull_remote(
            VersionStore(self.store_dir),
            remote,
            branch=branch or remote.default_branch,
            into_branch=into_branch,
            switch=switch,
            force=force,
        )

    def remote_fork(self, *, name: str, branch_name: str, remote_branch: str | None = None, switch: bool = False) -> dict[str, Any]:
        registry = RemoteRegistry(self.store_dir)
        remote = registry.get(name)
        if remote is None:
            raise ValueError(f"Unknown remote: {name}")
        return fork_remote(
            VersionStore(self.store_dir),
            remote,
            remote_branch=remote_branch or remote.default_branch,
            local_branch=branch_name,
            switch=switch,
        )


UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cortex Infrastructure UI</title>
  <style>
    :root {
      --bg: #f4efe6;
      --panel: #fff9f1;
      --ink: #1f1b18;
      --muted: #6e6258;
      --line: #d8cfc4;
      --accent: #0f6c5c;
      --accent-soft: #cde8e2;
      --warning: #8c5a13;
      --danger: #a43a2f;
      --shadow: 0 18px 45px rgba(63, 43, 19, 0.08);
      --radius: 20px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15, 108, 92, 0.16), transparent 30%),
        radial-gradient(circle at bottom right, rgba(164, 58, 47, 0.12), transparent 28%),
        var(--bg);
      min-height: 100vh;
    }
    .shell {
      display: grid;
      grid-template-columns: 270px 1fr;
      min-height: 100vh;
    }
    aside {
      padding: 28px 22px;
      border-right: 1px solid var(--line);
      background: rgba(255, 249, 241, 0.72);
      backdrop-filter: blur(14px);
    }
    .brand {
      margin-bottom: 28px;
    }
    .brand h1 {
      margin: 0;
      font-size: 1.7rem;
      letter-spacing: 0.02em;
    }
    .brand p {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.96rem;
    }
    .meta-card, .nav button, .panel, .result {
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      border-radius: var(--radius);
      background: var(--panel);
    }
    .meta-card {
      padding: 14px 16px;
      margin-bottom: 18px;
      font-size: 0.92rem;
      line-height: 1.45;
    }
    .nav {
      display: grid;
      gap: 10px;
    }
    .nav button {
      padding: 14px 16px;
      cursor: pointer;
      text-align: left;
      font: inherit;
      transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
    }
    .nav button.active {
      background: linear-gradient(135deg, var(--accent-soft), #eefbf8);
      border-color: rgba(15,108,92,0.34);
      transform: translateX(4px);
    }
    main {
      padding: 28px;
      display: grid;
      gap: 18px;
      align-content: start;
    }
    .hero {
      padding: 24px;
      background: linear-gradient(135deg, rgba(15,108,92,0.12), rgba(255,255,255,0.82));
      border: 1px solid rgba(15,108,92,0.16);
      border-radius: calc(var(--radius) + 6px);
      box-shadow: var(--shadow);
    }
    .hero h2 {
      margin: 0 0 8px;
      font-size: 2rem;
    }
    .hero p {
      margin: 0;
      max-width: 70ch;
      color: var(--muted);
      line-height: 1.5;
    }
    .panel {
      padding: 20px;
      display: none;
    }
    .panel.active { display: block; }
    .panel-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin-bottom: 16px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 0.92rem;
      color: var(--muted);
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: white;
      padding: 11px 12px;
      font: inherit;
      color: var(--ink);
    }
    textarea { min-height: 90px; resize: vertical; }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 14px 0 6px;
    }
    button.action {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      font: inherit;
    }
    button.subtle {
      background: #efe8de;
      color: var(--ink);
    }
    .result {
      padding: 18px;
      min-height: 180px;
      overflow: auto;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: white;
    }
    .card strong {
      display: block;
      font-size: 1.35rem;
      margin-top: 4px;
    }
    .status-pass { color: var(--accent); }
    .status-fail { color: var(--danger); }
    .pill {
      display: inline-block;
      border-radius: 999px;
      padding: 4px 9px;
      background: #efe8de;
      margin: 0 6px 6px 0;
      font-size: 0.82rem;
    }
    .list {
      display: grid;
      gap: 10px;
    }
    .item {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      background: white;
    }
    .item h4 {
      margin: 0 0 6px;
      font-size: 1rem;
    }
    .item p {
      margin: 0;
      color: var(--muted);
      line-height: 1.45;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.88rem;
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .danger { color: var(--danger); }
    .warning { color: var(--warning); }
    .empty {
      color: var(--muted);
      font-style: italic;
    }
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">
        <h1>Cortex Infra</h1>
        <p>Git for AI Memory, rendered as a local control plane instead of a pile of terminal commands.</p>
      </div>
      <div class="meta-card" id="meta-card">Loading...</div>
      <div class="nav">
        <button data-panel="review" class="active">Review</button>
        <button data-panel="blame">Blame</button>
        <button data-panel="history">History</button>
        <button data-panel="governance">Governance</button>
        <button data-panel="remote">Remote</button>
      </div>
    </aside>
    <main>
      <section class="hero">
        <h2>Memory Infrastructure</h2>
        <p>Review meaning-level drift, trace claims to receipts, audit history, lock down namespaces, and sync memory branches between agents without leaving the browser.</p>
      </section>

      <section id="panel-review" class="panel active">
        <div class="panel-grid">
          <label>Context file<input id="review-input-file" placeholder="/abs/path/context.json"></label>
          <label>Against ref<input id="review-against" value="HEAD"></label>
          <label>Current ref<input id="review-ref" value="HEAD"></label>
          <label>Fail on<input id="review-fail-on" value="blocking"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="runReview()">Run review</button>
          <button class="action subtle" onclick="fillDefaultContext('review-input-file')">Use default context</button>
        </div>
        <div id="review-result" class="result empty">Run a review to see structural and semantic drift.</div>
      </section>

      <section id="panel-blame" class="panel">
        <div class="panel-grid">
          <label>Context file<input id="blame-input-file" placeholder="/abs/path/context.json"></label>
          <label>Label<input id="blame-label" placeholder="Project Atlas"></label>
          <label>Node id<input id="blame-node-id" placeholder="optional"></label>
          <label>Ref<input id="blame-ref" value="HEAD"></label>
          <label>Source filter<input id="blame-source" placeholder="optional"></label>
          <label>Limit<input id="blame-limit" type="number" value="20"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="runBlame()">Trace claim</button>
          <button class="action subtle" onclick="fillDefaultContext('blame-input-file')">Use default context</button>
        </div>
        <div id="blame-result" class="result empty">Trace a claim back to versions, sources, and claim-ledger receipts.</div>
      </section>

      <section id="panel-history" class="panel">
        <div class="panel-grid">
          <label>Context file<input id="history-input-file" placeholder="/abs/path/context.json"></label>
          <label>Label<input id="history-label" placeholder="Project Atlas"></label>
          <label>Node id<input id="history-node-id" placeholder="optional"></label>
          <label>Ref<input id="history-ref" value="HEAD"></label>
          <label>Source filter<input id="history-source" placeholder="optional"></label>
          <label>Limit<input id="history-limit" type="number" value="20"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="runHistory()">Show history</button>
          <button class="action subtle" onclick="fillDefaultContext('history-input-file')">Use default context</button>
        </div>
        <div id="history-result" class="result empty">See the timeline of one memory claim across versions and claim events.</div>
      </section>

      <section id="panel-governance" class="panel">
        <div class="panel-grid">
          <label>Rule name<input id="gov-name" placeholder="protect-main"></label>
          <label>Actor pattern<input id="gov-actor-pattern" value="agent/*"></label>
          <label>Actions (comma-separated)<input id="gov-actions" value="write"></label>
          <label>Namespaces (comma-separated)<input id="gov-namespaces" value="main"></label>
          <label>Approval below confidence<input id="gov-confidence" type="number" step="0.01" placeholder="0.75"></label>
          <label>Approval tags (comma-separated)<input id="gov-tags" placeholder="active_priorities"></label>
          <label>Approval semantic changes (comma-separated)<input id="gov-change-types" placeholder="lifecycle_shift"></label>
          <label>Description<textarea id="gov-description" placeholder="Require review before low-confidence writes to main."></textarea></label>
        </div>
        <div class="actions">
          <button class="action" onclick="saveGovernance('allow')">Save allow rule</button>
          <button class="action subtle" onclick="saveGovernance('deny')">Save deny rule</button>
          <button class="action subtle" onclick="loadGovernance()">Refresh rules</button>
        </div>
        <div class="panel-grid">
          <label>Check actor<input id="gov-check-actor" value="agent/coder"></label>
          <label>Check action<input id="gov-check-action" value="write"></label>
          <label>Check namespace<input id="gov-check-namespace" value="main"></label>
          <label>Check input file<input id="gov-check-input-file" placeholder="/abs/path/context.json"></label>
          <label>Against ref<input id="gov-check-against" value="HEAD"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="checkGovernance()">Check access</button>
        </div>
        <div id="governance-result" class="result empty">Load rules, create protection policies, and preview approval gates.</div>
      </section>

      <section id="panel-remote" class="panel">
        <div class="panel-grid">
          <label>Remote name<input id="remote-name" value="origin"></label>
          <label>Remote path<input id="remote-path" placeholder="/abs/path/to/other/store"></label>
          <label>Default branch<input id="remote-default-branch" value="main"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="addRemote()">Add remote</button>
          <button class="action subtle" onclick="loadRemotes()">Refresh remotes</button>
        </div>
        <div class="panel-grid">
          <label>Push branch<input id="remote-push-branch" value="main"></label>
          <label>Push to branch<input id="remote-push-target" placeholder="optional"></label>
          <label>Pull branch<input id="remote-pull-branch" value="main"></label>
          <label>Into branch<input id="remote-pull-into" placeholder="remotes/origin/main"></label>
          <label>Fork local branch<input id="remote-fork-branch" value="agent/experiment"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="pushRemote()">Push</button>
          <button class="action subtle" onclick="pullRemote()">Pull</button>
          <button class="action subtle" onclick="forkRemote()">Fork</button>
        </div>
        <div id="remote-result" class="result empty">Manage explicit memory remotes and branch sync flows.</div>
      </section>
    </main>
  </div>

  <script>
    let defaultContext = "";

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Request failed");
      }
      return data;
    }

    function fillDefaultContext(id) {
      if (defaultContext) {
        document.getElementById(id).value = defaultContext;
      }
    }

    function renderKeyValue(obj) {
      return `<pre class="mono">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`;
    }

    function setResult(id, html) {
      const el = document.getElementById(id);
      el.classList.remove("empty");
      el.innerHTML = html;
    }

    function setError(id, err) {
      setResult(id, `<div class="danger"><strong>Error</strong><p>${escapeHtml(err.message || err)}</p></div>`);
    }

    async function loadMeta() {
      const data = await api("/api/meta");
      defaultContext = data.context_file || "";
      document.getElementById("meta-card").innerHTML = `
        <div><strong>Store</strong><br><span class="mono">${escapeHtml(data.store_dir)}</span></div>
        <div style="margin-top:10px;"><strong>Branch</strong><br><span class="mono">${escapeHtml(data.current_branch || "main")}</span></div>
        <div style="margin-top:10px;"><strong>HEAD</strong><br><span class="mono">${escapeHtml(data.head || "(empty)")}</span></div>
      `;
      if (defaultContext) {
        ["review-input-file", "blame-input-file", "history-input-file", "gov-check-input-file"].forEach((id) => {
          const el = document.getElementById(id);
          if (el && !el.value) el.value = defaultContext;
        });
      }
    }

    async function runReview() {
      try {
        const data = await api("/api/review", {
          method: "POST",
          body: JSON.stringify({
            input_file: document.getElementById("review-input-file").value || "",
            against: document.getElementById("review-against").value || "HEAD",
            ref: document.getElementById("review-ref").value || "HEAD",
            fail_on: document.getElementById("review-fail-on").value || "blocking",
          }),
        });
        const summary = data.summary || {};
        const semantic = (data.semantic_changes || []).slice(0, 12).map((item) => `
          <div class="item">
            <h4>${escapeHtml(item.type)}</h4>
            <p>${escapeHtml(item.description)}</p>
          </div>
        `).join("");
        setResult("review-result", `
          <div class="cards">
            <div class="card"><div>Status</div><strong class="status-${data.status}">${escapeHtml(data.status)}</strong></div>
            <div class="card"><div>Added</div><strong>${summary.added_nodes ?? 0}</strong></div>
            <div class="card"><div>Modified</div><strong>${summary.modified_nodes ?? 0}</strong></div>
            <div class="card"><div>Contradictions</div><strong>${summary.new_contradictions ?? 0}</strong></div>
            <div class="card"><div>Temporal gaps</div><strong>${summary.new_temporal_gaps ?? 0}</strong></div>
            <div class="card"><div>Semantic</div><strong>${summary.semantic_changes ?? 0}</strong></div>
          </div>
          <div class="list">${semantic || '<div class="empty">No semantic changes detected.</div>'}</div>
          <h3>Raw review</h3>
          ${renderKeyValue(data)}
        `);
      } catch (err) {
        setError("review-result", err);
      }
    }

    function renderBlameNodes(nodes) {
      if (!nodes.length) return '<div class="empty">No matching nodes found.</div>';
      return nodes.map((item) => {
        const node = item.node || {};
        const history = item.history || {};
        const claims = item.claim_lineage || {};
        return `
          <div class="item">
            <h4>${escapeHtml(node.label)} <span class="mono">${escapeHtml(node.id)}</span></h4>
            <div>${(node.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}</div>
            <p>${escapeHtml((item.why_present || []).join(" | ") || "No immediate explanation recorded.")}</p>
            <p><strong>Versions seen:</strong> ${history.versions_seen || 0} &nbsp; <strong>Claim events:</strong> ${claims.event_count || 0}</p>
            ${history.introduced_in ? `<p><strong>Introduced:</strong> <span class="mono">${escapeHtml(history.introduced_in.version_id)}</span> ${escapeHtml(history.introduced_in.message || "")}</p>` : ""}
          </div>
        `;
      }).join("");
    }

    async function runBlame() {
      try {
        const data = await api("/api/blame", {
          method: "POST",
          body: JSON.stringify({
            input_file: document.getElementById("blame-input-file").value || "",
            label: document.getElementById("blame-label").value || "",
            node_id: document.getElementById("blame-node-id").value || "",
            ref: document.getElementById("blame-ref").value || "HEAD",
            source: document.getElementById("blame-source").value || "",
            limit: Number(document.getElementById("blame-limit").value || 20),
          }),
        });
        setResult("blame-result", `${renderBlameNodes(data.nodes || [])}<h3>Raw blame</h3>${renderKeyValue(data)}`);
      } catch (err) {
        setError("blame-result", err);
      }
    }

    async function runHistory() {
      try {
        const data = await api("/api/history", {
          method: "POST",
          body: JSON.stringify({
            input_file: document.getElementById("history-input-file").value || "",
            label: document.getElementById("history-label").value || "",
            node_id: document.getElementById("history-node-id").value || "",
            ref: document.getElementById("history-ref").value || "HEAD",
            source: document.getElementById("history-source").value || "",
            limit: Number(document.getElementById("history-limit").value || 20),
          }),
        });
        setResult("history-result", `${renderBlameNodes(data.nodes || [])}<h3>Raw history</h3>${renderKeyValue(data)}`);
      } catch (err) {
        setError("history-result", err);
      }
    }

    async function loadGovernance() {
      try {
        const data = await api("/api/governance/rules");
        const rules = (data.rules || []).map((rule) => `
          <div class="item">
            <h4>${escapeHtml(rule.name)} <span class="pill">${escapeHtml(rule.effect)}</span></h4>
            <p>${escapeHtml(rule.description || "No description.")}</p>
            <p class="mono">actor=${escapeHtml(rule.actor_pattern)} actions=${escapeHtml((rule.actions || []).join(","))} namespaces=${escapeHtml((rule.namespaces || []).join(","))}</p>
            <div class="actions"><button class="action subtle" onclick="deleteGovernance('${encodeURIComponent(rule.name)}')">Delete</button></div>
          </div>
        `).join("") || '<div class="empty">No governance rules configured.</div>';
        setResult("governance-result", `<div class="list">${rules}</div>`);
      } catch (err) {
        setError("governance-result", err);
      }
    }

    async function saveGovernance(effect) {
      try {
        await api(`/api/governance/${effect}`, {
          method: "POST",
          body: JSON.stringify({
            name: document.getElementById("gov-name").value,
            actor_pattern: document.getElementById("gov-actor-pattern").value || "*",
            actions: document.getElementById("gov-actions").value.split(",").map((v) => v.trim()).filter(Boolean),
            namespaces: document.getElementById("gov-namespaces").value.split(",").map((v) => v.trim()).filter(Boolean),
            require_approval: true,
            approval_below_confidence: document.getElementById("gov-confidence").value ? Number(document.getElementById("gov-confidence").value) : null,
            approval_tags: document.getElementById("gov-tags").value.split(",").map((v) => v.trim()).filter(Boolean),
            approval_change_types: document.getElementById("gov-change-types").value.split(",").map((v) => v.trim()).filter(Boolean),
            description: document.getElementById("gov-description").value || "",
          }),
        });
        await loadGovernance();
      } catch (err) {
        setError("governance-result", err);
      }
    }

    async function deleteGovernance(name) {
      try {
        await api("/api/governance/delete", {
          method: "POST",
          body: JSON.stringify({ name: decodeURIComponent(name) }),
        });
        await loadGovernance();
      } catch (err) {
        setError("governance-result", err);
      }
    }

    async function checkGovernance() {
      try {
        const data = await api("/api/governance/check", {
          method: "POST",
          body: JSON.stringify({
            actor: document.getElementById("gov-check-actor").value,
            action: document.getElementById("gov-check-action").value,
            namespace: document.getElementById("gov-check-namespace").value,
            input_file: document.getElementById("gov-check-input-file").value || "",
            against: document.getElementById("gov-check-against").value || "",
          }),
        });
        setResult("governance-result", `<div class="item"><h4>${escapeHtml(data.allowed ? "ALLOW" : "DENY")}</h4><p>${escapeHtml((data.reasons || []).join(" | ") || "No additional reasons.")}</p></div><h3>Rules</h3>${renderKeyValue(data)}`);
      } catch (err) {
        setError("governance-result", err);
      }
    }

    async function loadRemotes() {
      try {
        const data = await api("/api/remotes");
        const remotes = (data.remotes || []).map((remote) => `
          <div class="item">
            <h4>${escapeHtml(remote.name)}</h4>
            <p class="mono">${escapeHtml(remote.store_path)}</p>
            <p>default branch: ${escapeHtml(remote.default_branch)}</p>
            <div class="actions"><button class="action subtle" onclick="removeRemote('${encodeURIComponent(remote.name)}')">Remove</button></div>
          </div>
        `).join("") || '<div class="empty">No remotes configured.</div>';
        setResult("remote-result", `<div class="list">${remotes}</div>`);
      } catch (err) {
        setError("remote-result", err);
      }
    }

    async function addRemote() {
      try {
        await api("/api/remote/add", {
          method: "POST",
          body: JSON.stringify({
            name: document.getElementById("remote-name").value,
            path: document.getElementById("remote-path").value,
            default_branch: document.getElementById("remote-default-branch").value || "main",
          }),
        });
        await loadRemotes();
      } catch (err) {
        setError("remote-result", err);
      }
    }

    async function removeRemote(name) {
      try {
        await api("/api/remote/remove", {
          method: "POST",
          body: JSON.stringify({ name: decodeURIComponent(name) }),
        });
        await loadRemotes();
      } catch (err) {
        setError("remote-result", err);
      }
    }

    async function pushRemote() {
      try {
        const data = await api("/api/remote/push", {
          method: "POST",
          body: JSON.stringify({
            name: document.getElementById("remote-name").value,
            branch: document.getElementById("remote-push-branch").value || "HEAD",
            to_branch: document.getElementById("remote-push-target").value || "",
          }),
        });
        setResult("remote-result", `<div class="item"><h4>Pushed</h4><p>${escapeHtml(data.branch)} -> ${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)}</p></div>${renderKeyValue(data)}`);
      } catch (err) {
        setError("remote-result", err);
      }
    }

    async function pullRemote() {
      try {
        const data = await api("/api/remote/pull", {
          method: "POST",
          body: JSON.stringify({
            name: document.getElementById("remote-name").value,
            branch: document.getElementById("remote-pull-branch").value || "",
            into_branch: document.getElementById("remote-pull-into").value || "",
          }),
        });
        setResult("remote-result", `<div class="item"><h4>Pulled</h4><p>${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)} -> ${escapeHtml(data.branch)}</p></div>${renderKeyValue(data)}`);
      } catch (err) {
        setError("remote-result", err);
      }
    }

    async function forkRemote() {
      try {
        const data = await api("/api/remote/fork", {
          method: "POST",
          body: JSON.stringify({
            name: document.getElementById("remote-name").value,
            branch_name: document.getElementById("remote-fork-branch").value,
            remote_branch: document.getElementById("remote-pull-branch").value || "",
          }),
        });
        setResult("remote-result", `<div class="item"><h4>Forked</h4><p>${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)} -> ${escapeHtml(data.branch)}</p></div>${renderKeyValue(data)}`);
      } catch (err) {
        setError("remote-result", err);
      }
    }

    document.querySelectorAll(".nav button").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".nav button").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
        button.classList.add("active");
        document.getElementById(`panel-${button.dataset.panel}`).classList.add("active");
      });
    });

    loadMeta().then(loadGovernance).then(loadRemotes).catch((err) => {
      document.getElementById("meta-card").innerHTML = `<span class="danger">${escapeHtml(err.message || err)}</span>`;
    });
  </script>
</body>
</html>
"""


def make_handler(backend: MemoryUIBackend):
    class MemoryUIHandler(BaseHTTPRequestHandler):
        server_version = "CortexUI/1.0"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, text: str, status: int = 200) -> None:
            data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def _handle_error(self, exc: Exception, status: int = 400) -> None:
            self._send_json({"status": "error", "error": str(exc)}, status=status)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(UI_HTML)
                return
            if parsed.path == "/api/meta":
                self._send_json(backend.meta())
                return
            if parsed.path == "/api/governance/rules":
                self._send_json(backend.list_governance_rules())
                return
            if parsed.path == "/api/remotes":
                self._send_json(backend.list_remotes())
                return
            self._send_json({"status": "error", "error": "Not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._read_json()
                path = self.path
                if path == "/api/review":
                    self._send_json(backend.review(**payload))
                    return
                if path == "/api/blame":
                    self._send_json(backend.blame(**payload))
                    return
                if path == "/api/history":
                    self._send_json(backend.history(**payload))
                    return
                if path == "/api/governance/allow":
                    self._send_json(backend.save_governance_rule(effect="allow", payload=payload))
                    return
                if path == "/api/governance/deny":
                    self._send_json(backend.save_governance_rule(effect="deny", payload=payload))
                    return
                if path == "/api/governance/delete":
                    self._send_json(backend.delete_governance_rule(payload["name"]))
                    return
                if path == "/api/governance/check":
                    self._send_json(backend.check_governance(**payload))
                    return
                if path == "/api/remote/add":
                    self._send_json(backend.add_remote(**payload))
                    return
                if path == "/api/remote/remove":
                    self._send_json(backend.remove_remote(payload["name"]))
                    return
                if path == "/api/remote/push":
                    self._send_json(backend.remote_push(**payload))
                    return
                if path == "/api/remote/pull":
                    self._send_json(backend.remote_pull(**payload))
                    return
                if path == "/api/remote/fork":
                    self._send_json(backend.remote_fork(**payload))
                    return
            except ValueError as exc:
                self._handle_error(exc, status=400)
                return
            except FileNotFoundError as exc:
                self._handle_error(exc, status=404)
                return
            except Exception as exc:  # pragma: no cover - defensive
                self._handle_error(exc, status=500)
                return
            self._send_json({"status": "error", "error": "Not found"}, status=404)

    return MemoryUIHandler


def start_ui_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    store_dir: str | Path = ".cortex",
    context_file: str | Path | None = None,
    open_browser: bool = False,
) -> tuple[ThreadingHTTPServer, str]:
    backend = MemoryUIBackend(store_dir=store_dir, context_file=context_file)
    server = ThreadingHTTPServer((host, port), make_handler(backend))
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    return server, url
