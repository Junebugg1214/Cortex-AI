"""
Small local web UI for Git-for-AI-Memory workflows.

Zero-dependency HTTP server with a single-page interface for review, blame,
history, governance, remote sync, indexing, and maintenance operations.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from cortex.cli import _load_graph
from cortex.embeddings import get_embedding_provider
from cortex.governance import GOVERNANCE_ACTIONS
from cortex.memory_ops import blame_memory_nodes
from cortex.review import parse_failure_policies, review_graphs
from cortex.schemas.memory_v1 import GovernanceRuleRecord, RemoteRecord
from cortex.service import MemoryService
from cortex.storage import get_storage_backend
from cortex.storage.base import StorageBackend


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


class MemoryUIBackend:
    def __init__(
        self,
        store_dir: str | Path,
        context_file: str | Path | None = None,
        backend: StorageBackend | None = None,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.context_file = Path(context_file).resolve() if context_file else None
        self.backend = backend or get_storage_backend(self.store_dir)
        self.service = MemoryService(store_dir=self.store_dir, context_file=self.context_file, backend=self.backend)

    def _backend_name(self) -> str:
        module_name = type(self.backend).__module__
        if module_name.endswith(".sqlite"):
            return "sqlite"
        return "filesystem"

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

    def _safe_index_status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        resolved_ref = self.backend.versions.resolve_ref(ref)
        if resolved_ref is None:
            provider = get_embedding_provider()
            return {
                "status": "ok",
                "backend": self._backend_name(),
                "persistent": self._backend_name() == "sqlite",
                "supported": self._backend_name() == "sqlite",
                "ref": ref,
                "resolved_ref": None,
                "indexed": False,
                "stale": False,
                "doc_count": 0,
                "updated_at": None,
                "last_indexed_commit": None,
                "last_indexed_at": None,
                "lag_commits": 0,
                "embedding_provider": provider.name,
                "embedding_enabled": provider.enabled,
                "embedding_indexed": False,
                "message": "No commits yet. Create or import memory before indexing.",
            }
        return self.backend.indexing.status(ref=ref)

    def _safe_metrics(self) -> dict[str, Any]:
        metrics = self.service.observability.metrics(
            index_status=self._safe_index_status(ref="HEAD"),
            backend=self._backend_name(),
            current_branch=self.backend.versions.current_branch(),
        )
        metrics["release"] = self.service.release()
        return metrics

    def health(self) -> dict[str, Any]:
        meta = self.meta()
        return {
            "status": "ok",
            "backend": meta["backend"],
            "store_dir": meta["store_dir"],
            "current_branch": meta["current_branch"],
            "head": meta["head"],
            "index": meta["index"],
            "release": meta["release"],
        }

    def meta(self) -> dict[str, Any]:
        versions = self.backend.versions
        current = versions.current_branch()
        default_context = self._default_context_file()
        return {
            "status": "ok",
            "store_dir": str(self.store_dir.resolve()),
            "context_file": str(default_context) if default_context else "",
            "default_context_available": default_context is not None,
            "backend": self._backend_name(),
            "current_branch": current,
            "head": versions.resolve_ref("HEAD"),
            "branch_count": len(versions.list_branches()),
            "index": self._safe_index_status(ref="HEAD"),
            "log_path": str(self.service.observability.log_path),
            "release": self.service.release(),
        }

    def review(
        self, *, input_file: str | None, against: str, ref: str = "HEAD", fail_on: str = "blocking"
    ) -> dict[str, Any]:
        if not (input_file or "").strip():
            return self.service.review(against=against, ref=ref, fail_on=fail_on)
        versions = self.backend.versions
        against_version = versions.resolve_ref(against)
        if against_version is None:
            raise ValueError(f"Unknown baseline ref: {against}")
        against_graph = versions.checkout(against_version)

        if input_file:
            input_path = self._resolve_input_file(input_file)
            current_graph = _load_graph(input_path)
            current_label = str(input_path)
        else:
            current_version = versions.resolve_ref(ref)
            if current_version is None:
                raise ValueError(f"Unknown current ref: {ref}")
            current_graph = versions.checkout(current_version)
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
        if not (input_file or "").strip():
            return self.service.blame(label=label, node_id=node_id, ref=ref, source=source, limit=limit)
        input_path = self._resolve_input_file(input_file)
        graph = _load_graph(input_path)
        return blame_memory_nodes(
            graph,
            label=label or None,
            node_id=node_id or None,
            store=self.backend.versions,
            ledger=self.backend.claims,
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
        if not (input_file or "").strip():
            return self.service.history(label=label, node_id=node_id, ref=ref, source=source, limit=limit)
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
        return {"rules": [rule.to_dict() for rule in self.backend.governance.list_rules()]}

    def save_governance_rule(self, *, effect: str, payload: dict[str, Any]) -> dict[str, Any]:
        actions = list(payload.get("actions") or payload.get("action") or [])
        namespaces = list(payload.get("namespaces") or payload.get("namespace") or [])
        invalid = [item for item in actions if item != "*" and item not in GOVERNANCE_ACTIONS]
        if invalid:
            raise ValueError(f"Unknown governance action(s): {', '.join(sorted(invalid))}")
        rule = GovernanceRuleRecord(
            tenant_id=self.backend.tenant_id,
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
        self.backend.governance.upsert_rule(rule)
        return {"status": "ok", "rule": rule.to_dict()}

    def delete_governance_rule(self, name: str) -> dict[str, Any]:
        removed = self.backend.governance.remove_rule(name)
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
            version_id = self.backend.versions.resolve_ref(against)
            if version_id is None:
                raise ValueError(f"Unknown baseline ref: {against}")
            baseline_graph = self.backend.versions.checkout(version_id)
        return self.backend.governance.authorize(
            actor,
            action,
            namespace,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        ).to_dict()

    def metrics(self) -> dict[str, Any]:
        return self._safe_metrics()

    def index_status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        return self._safe_index_status(ref=ref)

    def index_rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        if all_refs:
            branches = [branch for branch in self.backend.versions.list_branches() if branch.head]
            if not branches:
                status = self._safe_index_status(ref=ref)
                return {
                    "status": "ok",
                    "backend": self._backend_name(),
                    "persistent": status.get("persistent", False),
                    "supported": status.get("supported", False),
                    "ref": ref,
                    "all_refs": True,
                    "rebuilt": 0,
                    "indexed_versions": [],
                    "doc_count": 0,
                    "updated_at": None,
                    "last_indexed_commit": None,
                    "embedding_provider": status.get("embedding_provider", "disabled"),
                    "embedding_enabled": status.get("embedding_enabled", False),
                    "message": "No committed refs are available to rebuild.",
                }
        elif self.backend.versions.resolve_ref(ref) is None:
            status = self._safe_index_status(ref=ref)
            return {
                "status": "ok",
                "backend": self._backend_name(),
                "persistent": status.get("persistent", False),
                "supported": status.get("supported", False),
                "ref": ref,
                "all_refs": False,
                "rebuilt": 0,
                "indexed_versions": [],
                "doc_count": 0,
                "updated_at": None,
                "last_indexed_commit": None,
                "embedding_provider": status.get("embedding_provider", "disabled"),
                "embedding_enabled": status.get("embedding_enabled", False),
                "message": "Unknown ref or empty store. Commit memory before rebuilding indexes.",
            }
        return self.backend.indexing.rebuild(ref=ref, all_refs=all_refs)

    def prune_status(self, *, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.status(retention_days=retention_days)

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.prune(dry_run=dry_run, retention_days=retention_days)

    def prune_audit(self, *, limit: int = 20) -> dict[str, Any]:
        return {"status": "ok", "entries": self.backend.maintenance.audit_log(limit=limit)}

    def list_remotes(self) -> dict[str, Any]:
        return {
            "remotes": [
                remote.to_dict() | {"store_path": remote.resolved_store_path}
                for remote in self.backend.remotes.list_remotes()
            ]
        }

    def add_remote(self, *, name: str, path: str, default_branch: str = "main") -> dict[str, Any]:
        remote = RemoteRecord(
            tenant_id=self.backend.tenant_id,
            name=name,
            path=path,
            default_branch=default_branch,
        )
        self.backend.remotes.add_remote(remote)
        stored = next(item for item in self.backend.remotes.list_remotes() if item.name == name)
        return {"status": "ok", "remote": stored.to_dict() | {"store_path": stored.resolved_store_path}}

    def remove_remote(self, name: str) -> dict[str, Any]:
        removed = self.backend.remotes.remove_remote(name)
        return {"status": "ok" if removed else "missing", "name": name}

    def remote_push(
        self, *, name: str, branch: str = "HEAD", to_branch: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        return self.backend.remotes.push_remote(name, branch=branch, target_branch=to_branch, force=force)

    def remote_pull(
        self,
        *,
        name: str,
        branch: str | None = None,
        into_branch: str | None = None,
        switch: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        if branch is None:
            matching = next((item for item in self.backend.remotes.list_remotes() if item.name == name), None)
            if matching is None:
                raise ValueError(f"Unknown remote: {name}")
            branch = matching.default_branch
        return self.backend.remotes.pull_remote(
            name,
            branch=branch,
            into_branch=into_branch,
            switch=switch,
            force=force,
        )

    def remote_fork(
        self, *, name: str, branch_name: str, remote_branch: str | None = None, switch: bool = False
    ) -> dict[str, Any]:
        if remote_branch is None:
            matching = next((item for item in self.backend.remotes.list_remotes() if item.name == name), None)
            if matching is None:
                raise ValueError(f"Unknown remote: {name}")
            remote_branch = matching.default_branch
        return self.backend.remotes.fork_remote(
            name,
            remote_branch=remote_branch,
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
      --panel-strong: #fffdf8;
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
      grid-template-columns: 290px 1fr;
      min-height: 100vh;
    }
    aside {
      padding: 28px 22px;
      border-right: 1px solid var(--line);
      background: rgba(255, 249, 241, 0.78);
      backdrop-filter: blur(14px);
    }
    .brand { margin-bottom: 24px; }
    .brand h1 {
      margin: 0;
      font-size: 1.8rem;
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
    .meta-card strong {
      display: block;
      margin-bottom: 4px;
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
    .nav button.active,
    .nav button[aria-selected="true"] {
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
      max-width: 72ch;
      color: var(--muted);
      line-height: 1.5;
    }
    .panel {
      padding: 20px;
      display: none;
    }
    .panel.active { display: block; }
    .panel h3 {
      margin: 0 0 10px;
      font-size: 1.1rem;
    }
    .panel-copy {
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.5;
    }
    .panel-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin-bottom: 16px;
    }
    .split-results {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    }
    .stack {
      display: grid;
      gap: 16px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 0.92rem;
      color: var(--muted);
    }
    .checkbox {
      display: flex;
      gap: 10px;
      align-items: center;
      padding: 12px 14px;
      border-radius: 14px;
      background: white;
      border: 1px solid var(--line);
      color: var(--ink);
    }
    .checkbox input {
      width: auto;
      margin: 0;
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
    button.action[disabled] {
      opacity: 0.62;
      cursor: progress;
    }
    .result {
      padding: 18px;
      min-height: 150px;
      overflow: auto;
      background: var(--panel-strong);
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
    .danger { color: var(--danger); }
    .warning { color: var(--warning); }
    .empty {
      color: var(--muted);
      font-style: italic;
    }
    .helper {
      margin: -8px 0 8px;
      color: var(--muted);
      font-size: 0.88rem;
    }
    @media (max-width: 980px) {
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
        <p>Local-first memory infrastructure with a browser control plane for review, provenance, protection, sync, and runtime operations.</p>
      </div>
      <div class="meta-card" id="meta-card">Loading...</div>
      <div class="nav" role="tablist" aria-label="Cortex UI panels">
        <button data-panel="overview" class="active" role="tab" aria-selected="true">Overview</button>
        <button data-panel="review" role="tab" aria-selected="false">Review</button>
        <button data-panel="blame" role="tab" aria-selected="false">Blame</button>
        <button data-panel="history" role="tab" aria-selected="false">History</button>
        <button data-panel="governance" role="tab" aria-selected="false">Governance</button>
        <button data-panel="remote" role="tab" aria-selected="false">Remote</button>
        <button data-panel="operations" role="tab" aria-selected="false">Operations</button>
      </div>
    </aside>
    <main>
      <section class="hero">
        <h2>Memory Infrastructure</h2>
        <p>Review meaning-level drift, trace claims to receipts, audit branch history, protect namespaces, sync remotes, and operate indexing plus maintenance from one local console.</p>
      </section>

      <section id="panel-overview" class="panel active" role="tabpanel" aria-labelledby="overview">
        <h3>Overview</h3>
        <p class="panel-copy">This is the control-plane snapshot for the local store: backend, current branch, release contract, indexing health, and request telemetry.</p>
        <div id="overview-cards" class="cards"></div>
        <div class="actions">
          <button class="action" onclick="loadOverview(this)">Refresh overview</button>
          <button class="action subtle" onclick="loadMetrics(this)">Refresh metrics only</button>
        </div>
        <div class="split-results">
          <div id="overview-health" class="result empty">Health and release metadata will appear here.</div>
          <div id="overview-metrics" class="result empty">Request counts, error counts, and route timings will appear here.</div>
        </div>
      </section>

      <section id="panel-review" class="panel" role="tabpanel">
        <h3>Review</h3>
        <p class="panel-copy">Run semantic review against a stored ref or point at a graph file if you want to compare an uncommitted payload.</p>
        <div class="panel-grid">
          <label>Context file (optional)<input id="review-input-file" placeholder="/abs/path/context.json"></label>
          <label>Against ref<input id="review-against" value="HEAD"></label>
          <label>Current ref<input id="review-ref" value="HEAD"></label>
          <label>Fail on<input id="review-fail-on" value="blocking"></label>
        </div>
        <p class="helper">Leave the context file blank to review the stored ref directly.</p>
        <div class="actions">
          <button class="action" onclick="runReview(this)">Run review</button>
          <button class="action subtle" onclick="fillDefaultContext('review-input-file')">Use default context</button>
        </div>
        <div id="review-result" class="result empty">Run a review to see structural and semantic drift.</div>
      </section>

      <section id="panel-blame" class="panel" role="tabpanel">
        <h3>Blame</h3>
        <p class="panel-copy">Trace one memory node back through commits and claim lineage. You can inspect a stored ref or an explicit graph file.</p>
        <div class="panel-grid">
          <label>Context file (optional)<input id="blame-input-file" placeholder="/abs/path/context.json"></label>
          <label>Label<input id="blame-label" placeholder="Project Atlas"></label>
          <label>Node id<input id="blame-node-id" placeholder="optional"></label>
          <label>Ref<input id="blame-ref" value="HEAD"></label>
          <label>Source filter<input id="blame-source" placeholder="optional"></label>
          <label>Limit<input id="blame-limit" type="number" value="20" min="1"></label>
        </div>
        <p class="helper">Leave the context file blank to blame against the stored ref.</p>
        <div class="actions">
          <button class="action" onclick="runBlame(this)">Trace claim</button>
          <button class="action subtle" onclick="fillDefaultContext('blame-input-file')">Use default context</button>
        </div>
        <div id="blame-result" class="result empty">Trace a claim back to versions, sources, and claim-ledger receipts.</div>
      </section>

      <section id="panel-history" class="panel" role="tabpanel">
        <h3>History</h3>
        <p class="panel-copy">Inspect the timeline for one memory node without leaving the browser. It works against stored refs and uncommitted payloads.</p>
        <div class="panel-grid">
          <label>Context file (optional)<input id="history-input-file" placeholder="/abs/path/context.json"></label>
          <label>Label<input id="history-label" placeholder="Project Atlas"></label>
          <label>Node id<input id="history-node-id" placeholder="optional"></label>
          <label>Ref<input id="history-ref" value="HEAD"></label>
          <label>Source filter<input id="history-source" placeholder="optional"></label>
          <label>Limit<input id="history-limit" type="number" value="20" min="1"></label>
        </div>
        <p class="helper">Leave the context file blank to read history directly from the active store.</p>
        <div class="actions">
          <button class="action" onclick="runHistory(this)">Show history</button>
          <button class="action subtle" onclick="fillDefaultContext('history-input-file')">Use default context</button>
        </div>
        <div id="history-result" class="result empty">See the timeline of one memory claim across versions and claim events.</div>
      </section>

      <section id="panel-governance" class="panel" role="tabpanel">
        <h3>Governance</h3>
        <p class="panel-copy">Create or delete namespace rules, then preview whether a write would be allowed or require approval.</p>
        <div class="panel-grid">
          <label>Rule name<input id="gov-name" placeholder="protect-main"></label>
          <label>Actor pattern<input id="gov-actor-pattern" value="agent/*"></label>
          <label>Actions (comma-separated)<input id="gov-actions" value="write"></label>
          <label>Namespaces (comma-separated)<input id="gov-namespaces" value="main"></label>
          <label>Approval below confidence<input id="gov-confidence" type="number" step="0.01" placeholder="0.75"></label>
          <label>Approval tags (comma-separated)<input id="gov-tags" placeholder="active_priorities"></label>
          <label>Approval semantic changes (comma-separated)<input id="gov-change-types" placeholder="lifecycle_shift"></label>
          <label>Description<textarea id="gov-description" placeholder="Require review before low-confidence writes to main."></textarea></label>
          <label class="checkbox"><input id="gov-require-approval" type="checkbox"> Require approval when this rule matches</label>
        </div>
        <div class="actions">
          <button class="action" onclick="saveGovernance('allow', this)">Save allow rule</button>
          <button class="action subtle" onclick="saveGovernance('deny', this)">Save deny rule</button>
          <button class="action subtle" onclick="loadGovernance(this)">Refresh rules</button>
        </div>
        <div class="panel-grid">
          <label>Check actor<input id="gov-check-actor" value="agent/coder"></label>
          <label>Check action<input id="gov-check-action" value="write"></label>
          <label>Check namespace<input id="gov-check-namespace" value="main"></label>
          <label>Check input file (optional)<input id="gov-check-input-file" placeholder="/abs/path/context.json"></label>
          <label>Against ref<input id="gov-check-against" value="HEAD"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="checkGovernance(this)">Check access</button>
        </div>
        <div class="split-results">
          <div id="governance-rules-result" class="result empty">Configured governance rules will appear here.</div>
          <div id="governance-check-result" class="result empty">Access-check results will appear here.</div>
        </div>
      </section>

      <section id="panel-remote" class="panel" role="tabpanel">
        <h3>Remote</h3>
        <p class="panel-copy">Manage explicit remotes and run push, pull, or fork flows from the browser. Clicking “Use remote” will preload the form.</p>
        <div class="panel-grid">
          <label>Remote name<input id="remote-name" value="origin"></label>
          <label>Remote path<input id="remote-path" placeholder="/abs/path/to/other/store"></label>
          <label>Default branch<input id="remote-default-branch" value="main"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="addRemote(this)">Add remote</button>
          <button class="action subtle" onclick="loadRemotes(this)">Refresh remotes</button>
        </div>
        <div class="panel-grid">
          <label>Push branch<input id="remote-push-branch" value="main"></label>
          <label>Push to branch<input id="remote-push-target" placeholder="optional"></label>
          <label>Pull branch<input id="remote-pull-branch" value="main"></label>
          <label>Into branch<input id="remote-pull-into" placeholder="remotes/origin/main"></label>
          <label>Fork local branch<input id="remote-fork-branch" value="agent/experiment"></label>
        </div>
        <div class="actions">
          <button class="action" onclick="pushRemote(this)">Push</button>
          <button class="action subtle" onclick="pullRemote(this)">Pull</button>
          <button class="action subtle" onclick="forkRemote(this)">Fork</button>
        </div>
        <div class="split-results">
          <div id="remote-list-result" class="result empty">Configured remotes will appear here.</div>
          <div id="remote-activity-result" class="result empty">Push, pull, and fork activity will appear here.</div>
        </div>
      </section>

      <section id="panel-operations" class="panel" role="tabpanel">
        <h3>Operations</h3>
        <p class="panel-copy">Operate persistent indexing, inspect maintenance state, and run safe prune workflows with dry-run support.</p>
        <div class="stack">
          <div>
            <div class="panel-grid">
              <label>Index ref<input id="ops-index-ref" value="HEAD"></label>
              <label class="checkbox"><input id="ops-index-all-refs" type="checkbox"> Rebuild all refs</label>
            </div>
            <div class="actions">
              <button class="action" onclick="loadIndexStatus(this)">Refresh index status</button>
              <button class="action subtle" onclick="rebuildIndex(this)">Rebuild index</button>
            </div>
            <div id="ops-index-result" class="result empty">Index status, lag, and rebuild responses will appear here.</div>
          </div>
          <div>
            <div class="panel-grid">
              <label>Retention days<input id="ops-retention-days" type="number" value="7" min="0"></label>
              <label class="checkbox"><input id="ops-prune-dry-run" type="checkbox" checked> Dry run prune first</label>
              <label>Audit entries<input id="ops-audit-limit" type="number" value="20" min="1"></label>
            </div>
            <div class="actions">
              <button class="action" onclick="loadPruneStatus(this)">Refresh maintenance status</button>
              <button class="action subtle" onclick="runPrune(this)">Run prune</button>
              <button class="action subtle" onclick="loadPruneAudit(this)">Refresh audit</button>
            </div>
            <div class="split-results">
              <div id="ops-prune-result" class="result empty">Maintenance status and prune responses will appear here.</div>
              <div id="ops-audit-result" class="result empty">Prune audit entries will appear here.</div>
            </div>
          </div>
        </div>
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
      const headers = { ...(options.headers || {}) };
      if (options.body !== undefined) {
        headers["Content-Type"] = "application/json";
      }
      const res = await fetch(path, { ...options, headers });
      const text = await res.text();
      let data = {};
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (err) {
          data = { status: res.ok ? "ok" : "error", error: text };
        }
      }
      if (!res.ok) {
        throw new Error(data.error || data.message || `Request failed (${res.status})`);
      }
      return data;
    }

    function fillDefaultContext(id) {
      if (defaultContext) {
        document.getElementById(id).value = defaultContext;
      }
    }

    function requireValue(id, label) {
      const value = document.getElementById(id).value.trim();
      if (!value) {
        throw new Error(`${label} is required.`);
      }
      return value;
    }

    function commaList(id) {
      return document.getElementById(id).value.split(",").map((value) => value.trim()).filter(Boolean);
    }

    function numericValue(id, fallback) {
      const raw = document.getElementById(id).value;
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function checked(id) {
      return Boolean(document.getElementById(id).checked);
    }

    function shortRef(value) {
      if (!value) return "(empty)";
      return value.length > 14 ? `${value.slice(0, 14)}…` : value;
    }

    function renderKeyValue(obj) {
      return `<pre class="mono">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`;
    }

    function setResult(id, html) {
      const el = document.getElementById(id);
      el.classList.remove("empty");
      el.innerHTML = html;
    }

    function setEmpty(id, text) {
      const el = document.getElementById(id);
      el.classList.add("empty");
      el.textContent = text;
    }

    function setError(id, err) {
      setResult(id, `<div class="danger"><strong>Error</strong><p>${escapeHtml(err.message || err)}</p></div>`);
    }

    async function withBusy(trigger, label, work) {
      const button = trigger || null;
      const original = button ? button.textContent : "";
      if (button) {
        button.disabled = true;
        button.textContent = label;
      }
      try {
        return await work();
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = original;
        }
      }
    }

    function applyDefaultContext() {
      if (!defaultContext) return;
      ["review-input-file", "blame-input-file", "history-input-file", "gov-check-input-file"].forEach((id) => {
        const el = document.getElementById(id);
        if (el && !el.value) {
          el.value = defaultContext;
        }
      });
    }

    function renderBlameNodes(nodes) {
      if (!nodes.length) return '<div class="empty">No matching nodes found.</div>';
      return nodes.map((item) => {
        const node = item.node || {};
        const history = item.history || {};
        const claims = item.claim_lineage || {};
        return `
          <div class="item">
            <h4>${escapeHtml(node.label || "(unnamed)")} <span class="mono">${escapeHtml(node.id || "")}</span></h4>
            <div>${(node.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join("")}</div>
            <p>${escapeHtml((item.why_present || []).join(" | ") || "No immediate explanation recorded.")}</p>
            <p><strong>Versions seen:</strong> ${history.versions_seen || 0} &nbsp; <strong>Claim events:</strong> ${claims.event_count || 0}</p>
            ${history.introduced_in ? `<p><strong>Introduced:</strong> <span class="mono">${escapeHtml(history.introduced_in.version_id)}</span> ${escapeHtml(history.introduced_in.message || "")}</p>` : ""}
          </div>
        `;
      }).join("");
    }

    function renderOverviewCards(meta, metrics, pruneStatus) {
      const index = meta.index || {};
      return `
        <div class="card"><div>Backend</div><strong>${escapeHtml(meta.backend || "filesystem")}</strong></div>
        <div class="card"><div>Branch</div><strong>${escapeHtml(meta.current_branch || "main")}</strong></div>
        <div class="card"><div>HEAD</div><strong class="mono">${escapeHtml(shortRef(meta.head))}</strong></div>
        <div class="card"><div>Release</div><strong>${escapeHtml(meta.release?.project_version || "dev")}</strong></div>
        <div class="card"><div>Index lag</div><strong>${escapeHtml(String(index.lag_commits ?? 0))}</strong></div>
        <div class="card"><div>Requests</div><strong>${escapeHtml(String(metrics.requests_total ?? 0))}</strong></div>
        <div class="card"><div>Errors</div><strong>${escapeHtml(String(metrics.errors_total ?? 0))}</strong></div>
        <div class="card"><div>Stale artifacts</div><strong>${escapeHtml(String((pruneStatus.stale_merge_artifacts || []).length))}</strong></div>
      `;
    }

    function updateMetaCard(meta) {
      const index = meta.index || {};
      document.getElementById("meta-card").innerHTML = `
        <div><strong>Store</strong><span class="mono">${escapeHtml(meta.store_dir)}</span></div>
        <div style="margin-top:10px;"><strong>Backend</strong><span class="mono">${escapeHtml(meta.backend || "filesystem")}</span></div>
        <div style="margin-top:10px;"><strong>Branch</strong><span class="mono">${escapeHtml(meta.current_branch || "main")}</span></div>
        <div style="margin-top:10px;"><strong>HEAD</strong><span class="mono">${escapeHtml(meta.head || "(empty)")}</span></div>
        <div style="margin-top:10px;"><strong>Index</strong><span class="mono">${escapeHtml(index.persistent ? "persistent" : "graph checkout")}</span></div>
        <div style="margin-top:10px;"><strong>Logs</strong><span class="mono">${escapeHtml(meta.log_path || "(not configured)")}</span></div>
      `;
    }

    async function loadOverview(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        const [meta, health, metrics, pruneStatus] = await Promise.all([
          api("/api/meta"),
          api("/api/health"),
          api("/api/metrics"),
          api("/api/prune/status"),
        ]);
        defaultContext = meta.context_file || "";
        applyDefaultContext();
        updateMetaCard(meta);
        document.getElementById("overview-cards").innerHTML = renderOverviewCards(meta, metrics, pruneStatus);
        setResult("overview-health", renderKeyValue(health));
        setResult("overview-metrics", renderKeyValue(metrics));
        return meta;
      });
    }

    async function loadMetrics(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        const metrics = await api("/api/metrics");
        setResult("overview-metrics", renderKeyValue(metrics));
      });
    }

    async function runReview(trigger) {
      return withBusy(trigger, "Reviewing...", async () => {
        try {
          const data = await api("/api/review", {
            method: "POST",
            body: JSON.stringify({
              input_file: document.getElementById("review-input-file").value.trim(),
              against: requireValue("review-against", "Against ref"),
              ref: document.getElementById("review-ref").value.trim() || "HEAD",
              fail_on: document.getElementById("review-fail-on").value.trim() || "blocking",
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
      });
    }

    async function runBlame(trigger) {
      return withBusy(trigger, "Tracing...", async () => {
        try {
          const data = await api("/api/blame", {
            method: "POST",
            body: JSON.stringify({
              input_file: document.getElementById("blame-input-file").value.trim(),
              label: document.getElementById("blame-label").value.trim(),
              node_id: document.getElementById("blame-node-id").value.trim(),
              ref: document.getElementById("blame-ref").value.trim() || "HEAD",
              source: document.getElementById("blame-source").value.trim(),
              limit: numericValue("blame-limit", 20),
            }),
          });
          setResult("blame-result", `${renderBlameNodes(data.nodes || [])}<h3>Raw blame</h3>${renderKeyValue(data)}`);
        } catch (err) {
          setError("blame-result", err);
        }
      });
    }

    async function runHistory(trigger) {
      return withBusy(trigger, "Loading...", async () => {
        try {
          const data = await api("/api/history", {
            method: "POST",
            body: JSON.stringify({
              input_file: document.getElementById("history-input-file").value.trim(),
              label: document.getElementById("history-label").value.trim(),
              node_id: document.getElementById("history-node-id").value.trim(),
              ref: document.getElementById("history-ref").value.trim() || "HEAD",
              source: document.getElementById("history-source").value.trim(),
              limit: numericValue("history-limit", 20),
            }),
          });
          setResult("history-result", `${renderBlameNodes(data.nodes || [])}<h3>Raw history</h3>${renderKeyValue(data)}`);
        } catch (err) {
          setError("history-result", err);
        }
      });
    }

    async function loadGovernance(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const data = await api("/api/governance/rules");
          const rules = (data.rules || []).map((rule) => `
            <div class="item">
              <h4>${escapeHtml(rule.name)} <span class="pill">${escapeHtml(rule.effect)}</span></h4>
              <p>${escapeHtml(rule.description || "No description.")}</p>
              <p class="mono">actor=${escapeHtml(rule.actor_pattern)} actions=${escapeHtml((rule.actions || []).join(","))} namespaces=${escapeHtml((rule.namespaces || []).join(","))}</p>
              <div class="actions">
                <button class="action subtle" onclick="deleteGovernance('${encodeURIComponent(rule.name)}', this)">Delete</button>
              </div>
            </div>
          `).join("") || '<div class="empty">No governance rules configured.</div>';
          setResult("governance-rules-result", `<div class="list">${rules}</div>`);
        } catch (err) {
          setError("governance-rules-result", err);
        }
      });
    }

    async function saveGovernance(effect, trigger) {
      return withBusy(trigger, "Saving...", async () => {
        try {
          await api(`/api/governance/${effect}`, {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("gov-name", "Rule name"),
              actor_pattern: document.getElementById("gov-actor-pattern").value.trim() || "*",
              actions: commaList("gov-actions"),
              namespaces: commaList("gov-namespaces"),
              require_approval: checked("gov-require-approval"),
              approval_below_confidence: document.getElementById("gov-confidence").value ? Number(document.getElementById("gov-confidence").value) : null,
              approval_tags: commaList("gov-tags"),
              approval_change_types: commaList("gov-change-types"),
              description: document.getElementById("gov-description").value.trim(),
            }),
          });
          setResult("governance-check-result", `<div class="item"><h4>Saved</h4><p>The ${escapeHtml(effect)} rule was saved successfully.</p></div>`);
          await loadGovernance();
        } catch (err) {
          setError("governance-check-result", err);
        }
      });
    }

    async function deleteGovernance(name, trigger) {
      return withBusy(trigger, "Deleting...", async () => {
        try {
          await api("/api/governance/delete", {
            method: "POST",
            body: JSON.stringify({ name: decodeURIComponent(name) }),
          });
          setResult("governance-check-result", `<div class="item"><h4>Deleted</h4><p>Rule ${escapeHtml(decodeURIComponent(name))} was removed.</p></div>`);
          await loadGovernance();
        } catch (err) {
          setError("governance-check-result", err);
        }
      });
    }

    async function checkGovernance(trigger) {
      return withBusy(trigger, "Checking...", async () => {
        try {
          const data = await api("/api/governance/check", {
            method: "POST",
            body: JSON.stringify({
              actor: requireValue("gov-check-actor", "Actor"),
              action: requireValue("gov-check-action", "Action"),
              namespace: requireValue("gov-check-namespace", "Namespace"),
              input_file: document.getElementById("gov-check-input-file").value.trim(),
              against: document.getElementById("gov-check-against").value.trim(),
            }),
          });
          setResult("governance-check-result", `
            <div class="item">
              <h4>${escapeHtml(data.allowed ? "ALLOW" : "DENY")}</h4>
              <p>${escapeHtml((data.reasons || []).join(" | ") || "No additional reasons.")}</p>
            </div>
            ${renderKeyValue(data)}
          `);
        } catch (err) {
          setError("governance-check-result", err);
        }
      });
    }

    function selectRemote(name, defaultBranch) {
      const resolvedName = decodeURIComponent(name || "");
      const resolvedBranch = decodeURIComponent(defaultBranch || "");
      document.getElementById("remote-name").value = resolvedName;
      if (resolvedBranch) {
        document.getElementById("remote-default-branch").value = resolvedBranch;
        document.getElementById("remote-pull-branch").value = resolvedBranch;
      }
    }

    async function loadRemotes(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const data = await api("/api/remotes");
          const remotes = (data.remotes || []).map((remote) => `
            <div class="item">
              <h4>${escapeHtml(remote.name)}</h4>
              <p class="mono">${escapeHtml(remote.store_path)}</p>
              <p>default branch: ${escapeHtml(remote.default_branch)}</p>
              <div class="actions">
                <button class="action subtle" onclick="selectRemote('${encodeURIComponent(remote.name)}', '${encodeURIComponent(remote.default_branch)}')">Use remote</button>
                <button class="action subtle" onclick="removeRemote('${encodeURIComponent(remote.name)}', this)">Remove</button>
              </div>
            </div>
          `).join("") || '<div class="empty">No remotes configured.</div>';
          setResult("remote-list-result", `<div class="list">${remotes}</div>`);
        } catch (err) {
          setError("remote-list-result", err);
        }
      });
    }

    async function addRemote(trigger) {
      return withBusy(trigger, "Adding...", async () => {
        try {
          await api("/api/remote/add", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              path: requireValue("remote-path", "Remote path"),
              default_branch: document.getElementById("remote-default-branch").value.trim() || "main",
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Remote added</h4><p>The remote is ready for sync operations.</p></div>`);
          await loadRemotes();
          await loadOverview();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function removeRemote(name, trigger) {
      return withBusy(trigger, "Removing...", async () => {
        try {
          await api("/api/remote/remove", {
            method: "POST",
            body: JSON.stringify({ name: decodeURIComponent(name) }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Remote removed</h4><p>${escapeHtml(decodeURIComponent(name))} is no longer configured.</p></div>`);
          await loadRemotes();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function pushRemote(trigger) {
      return withBusy(trigger, "Pushing...", async () => {
        try {
          const data = await api("/api/remote/push", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              branch: document.getElementById("remote-push-branch").value.trim() || "HEAD",
              to_branch: document.getElementById("remote-push-target").value.trim(),
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Pushed</h4><p>${escapeHtml(data.branch)} -> ${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)}</p></div>${renderKeyValue(data)}`);
          await loadOverview();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function pullRemote(trigger) {
      return withBusy(trigger, "Pulling...", async () => {
        try {
          const data = await api("/api/remote/pull", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              branch: document.getElementById("remote-pull-branch").value.trim(),
              into_branch: document.getElementById("remote-pull-into").value.trim(),
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Pulled</h4><p>${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)} -> ${escapeHtml(data.branch)}</p></div>${renderKeyValue(data)}`);
          await loadOverview();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function forkRemote(trigger) {
      return withBusy(trigger, "Forking...", async () => {
        try {
          const data = await api("/api/remote/fork", {
            method: "POST",
            body: JSON.stringify({
              name: requireValue("remote-name", "Remote name"),
              branch_name: requireValue("remote-fork-branch", "Fork branch name"),
              remote_branch: document.getElementById("remote-pull-branch").value.trim(),
            }),
          });
          setResult("remote-activity-result", `<div class="item"><h4>Forked</h4><p>${escapeHtml(data.remote)}:${escapeHtml(data.remote_branch)} -> ${escapeHtml(data.branch)}</p></div>${renderKeyValue(data)}`);
          await loadOverview();
        } catch (err) {
          setError("remote-activity-result", err);
        }
      });
    }

    async function loadIndexStatus(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const ref = document.getElementById("ops-index-ref").value.trim() || "HEAD";
          const data = await api(`/api/index/status?ref=${encodeURIComponent(ref)}`);
          setResult("ops-index-result", renderKeyValue(data));
        } catch (err) {
          setError("ops-index-result", err);
        }
      });
    }

    async function rebuildIndex(trigger) {
      return withBusy(trigger, "Rebuilding...", async () => {
        try {
          const data = await api("/api/index/rebuild", {
            method: "POST",
            body: JSON.stringify({
              ref: document.getElementById("ops-index-ref").value.trim() || "HEAD",
              all_refs: checked("ops-index-all-refs"),
            }),
          });
          setResult("ops-index-result", renderKeyValue(data));
          await loadOverview();
        } catch (err) {
          setError("ops-index-result", err);
        }
      });
    }

    async function loadPruneStatus(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const retention = numericValue("ops-retention-days", 7);
          const data = await api(`/api/prune/status?retention_days=${encodeURIComponent(retention)}`);
          setResult("ops-prune-result", renderKeyValue(data));
        } catch (err) {
          setError("ops-prune-result", err);
        }
      });
    }

    async function runPrune(trigger) {
      return withBusy(trigger, checked("ops-prune-dry-run") ? "Dry running..." : "Pruning...", async () => {
        try {
          const data = await api("/api/prune", {
            method: "POST",
            body: JSON.stringify({
              dry_run: checked("ops-prune-dry-run"),
              retention_days: numericValue("ops-retention-days", 7),
            }),
          });
          setResult("ops-prune-result", renderKeyValue(data));
          await loadPruneAudit();
          await loadOverview();
        } catch (err) {
          setError("ops-prune-result", err);
        }
      });
    }

    async function loadPruneAudit(trigger) {
      return withBusy(trigger, "Refreshing...", async () => {
        try {
          const limit = numericValue("ops-audit-limit", 20);
          const data = await api(`/api/prune/audit?limit=${encodeURIComponent(limit)}`);
          if (!(data.entries || []).length) {
            setEmpty("ops-audit-result", "No prune audit entries yet.");
            return;
          }
          setResult("ops-audit-result", renderKeyValue(data));
        } catch (err) {
          setError("ops-audit-result", err);
        }
      });
    }

    function activatePanel(panelName, updateHash = true) {
      const name = panelName || "overview";
      document.querySelectorAll(".nav button").forEach((item) => {
        const selected = item.dataset.panel === name;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-selected", selected ? "true" : "false");
      });
      document.querySelectorAll(".panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `panel-${name}`);
      });
      if (updateHash) {
        history.replaceState(null, "", `#${name}`);
      }
    }

    document.querySelectorAll(".nav button").forEach((button) => {
      button.addEventListener("click", () => activatePanel(button.dataset.panel));
    });
    window.addEventListener("hashchange", () => {
      activatePanel(window.location.hash.replace(/^#/, "") || "overview", false);
    });

    async function bootstrap() {
      try {
        activatePanel(window.location.hash.replace(/^#/, "") || "overview", false);
        await loadOverview();
        await Promise.all([
          loadGovernance(),
          loadRemotes(),
          loadIndexStatus(),
          loadPruneStatus(),
          loadPruneAudit(),
        ]);
      } catch (err) {
        document.getElementById("meta-card").innerHTML = `<span class="danger">${escapeHtml(err.message || err)}</span>`;
      }
    }

    bootstrap();
  </script>
</body>
</html>
"""


def make_handler(backend: MemoryUIBackend):
    def query_value(parsed, key: str, default: str = "") -> str:
        return parse_qs(parsed.query).get(key, [default])[0]

    def query_int(parsed, key: str, default: int) -> int:
        raw = query_value(parsed, key, "")
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid integer for {key}: {raw}") from exc

    class MemoryUIHandler(BaseHTTPRequestHandler):
        server_version = "CortexUI/1.0"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200, *, request_id: str = "") -> None:
            data = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            if request_id:
                self.send_header("X-Request-ID", request_id)
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, text: str, status: int = 200, *, request_id: str = "") -> None:
            data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
            if request_id:
                self.send_header("X-Request-ID", request_id)
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def _log_request(
            self,
            *,
            request_id: str,
            method: str,
            path: str,
            started_at: float,
            status: int,
            error: str = "",
        ) -> None:
            backend.service.observability.record_request(
                request_id=request_id,
                method=method,
                path=path,
                status=status,
                duration_ms=(perf_counter() - started_at) * 1000,
                namespace=backend.backend.versions.current_branch(),
                backend=backend._backend_name(),
                index_lag_commits=backend._safe_index_status(ref="HEAD").get("lag_commits"),
                error=error,
            )

        def do_GET(self) -> None:  # noqa: N802
            request_id = uuid4().hex[:16]
            started_at = perf_counter()
            status = 200
            error = ""
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(UI_HTML, request_id=request_id)
                    return
                if parsed.path == "/api/meta":
                    self._send_json(backend.meta(), request_id=request_id)
                    return
                if parsed.path == "/api/health":
                    self._send_json(backend.health(), request_id=request_id)
                    return
                if parsed.path == "/api/metrics":
                    self._send_json(backend.metrics(), request_id=request_id)
                    return
                if parsed.path == "/api/governance/rules":
                    self._send_json(backend.list_governance_rules(), request_id=request_id)
                    return
                if parsed.path == "/api/remotes":
                    self._send_json(backend.list_remotes(), request_id=request_id)
                    return
                if parsed.path == "/api/index/status":
                    self._send_json(
                        backend.index_status(ref=query_value(parsed, "ref", "HEAD")),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/prune/status":
                    self._send_json(
                        backend.prune_status(retention_days=query_int(parsed, "retention_days", 7)),
                        request_id=request_id,
                    )
                    return
                if parsed.path == "/api/prune/audit":
                    self._send_json(
                        backend.prune_audit(limit=query_int(parsed, "limit", 20)),
                        request_id=request_id,
                    )
                    return
                status = 404
                error = "Not found"
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except ValueError as exc:
                status = 400
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except FileNotFoundError as exc:
                status = 404
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except Exception as exc:  # pragma: no cover - defensive
                status = 500
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            finally:
                self._log_request(
                    request_id=request_id,
                    method="GET",
                    path=self.path,
                    started_at=started_at,
                    status=status,
                    error=error,
                )

        def do_POST(self) -> None:  # noqa: N802
            request_id = uuid4().hex[:16]
            started_at = perf_counter()
            status = 200
            error = ""
            try:
                payload = self._read_json()
                path = self.path
                if path == "/api/review":
                    self._send_json(backend.review(**payload), request_id=request_id)
                    return
                if path == "/api/blame":
                    self._send_json(backend.blame(**payload), request_id=request_id)
                    return
                if path == "/api/history":
                    self._send_json(backend.history(**payload), request_id=request_id)
                    return
                if path == "/api/governance/allow":
                    self._send_json(
                        backend.save_governance_rule(effect="allow", payload=payload), request_id=request_id
                    )
                    return
                if path == "/api/governance/deny":
                    self._send_json(backend.save_governance_rule(effect="deny", payload=payload), request_id=request_id)
                    return
                if path == "/api/governance/delete":
                    self._send_json(backend.delete_governance_rule(payload["name"]), request_id=request_id)
                    return
                if path == "/api/governance/check":
                    self._send_json(backend.check_governance(**payload), request_id=request_id)
                    return
                if path == "/api/remote/add":
                    self._send_json(backend.add_remote(**payload), request_id=request_id)
                    return
                if path == "/api/remote/remove":
                    self._send_json(backend.remove_remote(payload["name"]), request_id=request_id)
                    return
                if path == "/api/remote/push":
                    self._send_json(backend.remote_push(**payload), request_id=request_id)
                    return
                if path == "/api/remote/pull":
                    self._send_json(backend.remote_pull(**payload), request_id=request_id)
                    return
                if path == "/api/remote/fork":
                    self._send_json(backend.remote_fork(**payload), request_id=request_id)
                    return
                if path == "/api/index/rebuild":
                    self._send_json(backend.index_rebuild(**payload), request_id=request_id)
                    return
                if path == "/api/prune":
                    self._send_json(backend.prune(**payload), request_id=request_id)
                    return
            except ValueError as exc:
                status = 400
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except FileNotFoundError as exc:
                status = 404
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            except Exception as exc:  # pragma: no cover - defensive
                status = 500
                error = str(exc)
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            else:
                status = 404
                error = "Not found"
                self._send_json({"status": "error", "error": error}, status=status, request_id=request_id)
            finally:
                self._log_request(
                    request_id=request_id,
                    method="POST",
                    path=self.path,
                    started_at=started_at,
                    status=status,
                    error=error,
                )

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
