import io
import json

from cortex.claims import ClaimEvent, ClaimLedger
from cortex.graph import CortexGraph, Node
from cortex.storage import build_sqlite_backend
from cortex.upai.versioning import VersionStore
from cortex.webapp import UI_HTML, MemoryUIBackend, make_handler


def _write_graph(path, graph: CortexGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def _invoke_handler(handler_cls, *, path: str, method: str = "GET", payload: dict | None = None):
    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.command = method
    handler.request_version = "HTTP/1.1"
    handler.rfile = io.BytesIO(json.dumps(payload).encode("utf-8") if payload is not None else b"")
    handler.wfile = io.BytesIO()
    handler.headers = {"Content-Length": str(handler.rfile.getbuffer().nbytes)}
    handler._status = 200
    handler._headers = {}

    def send_response(code, message=None):  # noqa: ARG001
        handler._status = code

    def send_header(key, value):
        handler._headers[key] = value

    def end_headers():
        return None

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers

    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    body = handler.wfile.getvalue().decode("utf-8")
    return handler._status, handler._headers, body


def test_webapp_html_mentions_current_primary_surfaces():
    assert "Portable AI context, without the archaeology" in UI_HTML
    assert "Workspace Overview" in UI_HTML
    assert "Quick actions" in UI_HTML
    assert "Remember & sync" in UI_HTML
    assert "Sync all" in UI_HTML
    assert "Connected Tools" in UI_HTML
    assert "Freshness & Gaps" in UI_HTML
    assert "Review & Trace" in UI_HTML
    assert "Advanced Controls" in UI_HTML
    assert "/api/portability/scan" in UI_HTML
    assert "/api/portability/status" in UI_HTML
    assert "/api/portability/audit" in UI_HTML
    assert "/api/portability/context" in UI_HTML
    assert "/api/portability/sync" in UI_HTML
    assert "/api/portability/remember" in UI_HTML


def test_webapp_backend_meta_review_and_blame(tmp_path):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)
    context_path = tmp_path / "context.json"

    baseline = CortexGraph()
    baseline.add_node(
        Node(
            id="n1",
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            confidence=0.7,
            provenance=[{"source": "import-a", "method": "extract"}],
            status="planned",
        )
    )
    baseline_version = store.commit(baseline, "baseline")

    current = CortexGraph()
    node = Node(
        id="n1",
        canonical_id="n1",
        label="PostgreSQL",
        aliases=["postgres"],
        tags=["technical_expertise"],
        confidence=0.95,
        provenance=[{"source": "manual-a", "method": "manual"}],
        status="active",
        valid_from="2026-03-23T00:00:00Z",
    )
    current.add_node(node)
    _write_graph(context_path, current)

    ledger = ClaimLedger(store_dir)
    ledger.append(
        ClaimEvent.from_node(
            node,
            op="assert",
            source="manual-a",
            method="manual_set",
            version_id=baseline_version.version_id,
            timestamp="2026-03-23T00:00:00Z",
        )
    )

    backend = MemoryUIBackend(store_dir=store_dir, context_file=context_path)
    meta = backend.meta()
    review = backend.review(input_file=str(context_path), against="HEAD", fail_on="blocking")
    blame = backend.blame(input_file=str(context_path), label="postgres", ref="HEAD", limit=10)
    history = backend.history(input_file=str(context_path), label="postgres", ref="HEAD", limit=10)

    assert meta["current_branch"] == "main"
    assert meta["context_file"] == str(context_path.resolve())
    assert review["summary"]["semantic_changes"] >= 1
    assert any(change["type"] == "lifecycle_shift" for change in review["semantic_changes"])
    assert blame["nodes"][0]["node"]["label"] == "PostgreSQL"
    assert blame["nodes"][0]["claim_lineage"]["event_count"] == 1
    assert history["nodes"][0]["history"]["versions_seen"] == 1


def test_webapp_backend_governance_and_remotes(tmp_path):
    local_store_dir = tmp_path / "local" / ".cortex"
    remote_root = tmp_path / "remote"
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    context_path = tmp_path / "local" / "context.json"
    _write_graph(context_path, graph)
    local_commit = VersionStore(local_store_dir).commit(graph, "baseline").version_id

    backend = MemoryUIBackend(store_dir=local_store_dir, context_file=context_path)
    allow = backend.save_governance_rule(
        effect="allow",
        payload={
            "name": "protect-main",
            "actor_pattern": "agent/*",
            "actions": ["write"],
            "namespaces": ["main"],
            "require_approval": True,
        },
    )
    rules = backend.list_governance_rules()
    check = backend.check_governance(actor="agent/coder", action="write", namespace="main")

    remote_add = backend.add_remote(name="origin", path=str(remote_root), default_branch="main")
    remote_list = backend.list_remotes()
    push = backend.remote_push(name="origin", branch="main")

    clone_store_dir = tmp_path / "clone" / ".cortex"
    clone_backend = MemoryUIBackend(store_dir=clone_store_dir)
    clone_backend.add_remote(name="origin", path=str(remote_root), default_branch="main")
    pull = clone_backend.remote_pull(name="origin", branch="main", into_branch="imported/main")
    fork = clone_backend.remote_fork(name="origin", branch_name="agent/experiment", remote_branch="main")

    assert allow["rule"]["name"] == "protect-main"
    assert rules["rules"][0]["name"] == "protect-main"
    assert check["allowed"] is True
    assert check["require_approval"] is True
    assert remote_add["remote"]["name"] == "origin"
    assert remote_list["remotes"][0]["name"] == "origin"
    assert push["head"] == local_commit
    assert pull["branch"] == "imported/main"
    assert fork["forked"] is True


def test_webapp_backend_supports_stored_ref_ops_without_context_file(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    node = Node(
        id="n1",
        canonical_id="n1",
        label="Project Atlas",
        aliases=["atlas"],
        tags=["active_priorities"],
        confidence=0.92,
        provenance=[{"source": "manual-a", "method": "manual"}],
        status="active",
    )
    graph.add_node(node)
    commit = backend.versions.commit(graph, "baseline")
    backend.claims.append(
        ClaimEvent.from_node(
            node,
            op="assert",
            source="manual-a",
            method="manual_set",
            version_id=commit.version_id,
            timestamp="2026-03-23T00:00:00Z",
        )
    )

    ui = MemoryUIBackend(store_dir=store_dir, backend=backend)

    meta = ui.meta()
    health = ui.health()
    index = ui.index_status(ref="HEAD")
    rebuild = ui.index_rebuild(ref="HEAD")
    prune_status = ui.prune_status(retention_days=7)
    prune = ui.prune(dry_run=True, retention_days=7)
    audit = ui.prune_audit(limit=10)
    blame = ui.blame(input_file=None, label="atlas", ref="HEAD", limit=10)
    history = ui.history(input_file=None, label="atlas", ref="HEAD", limit=10)

    assert meta["backend"] == "sqlite"
    assert meta["index"]["persistent"] is True
    assert health["release"]["project_version"] == meta["release"]["project_version"]
    assert index["last_indexed_commit"] == commit.version_id
    assert rebuild["rebuilt"] == 1
    assert prune_status["backend"] == "sqlite"
    assert prune["dry_run"] is True
    assert audit["entries"] == []
    assert blame["nodes"][0]["node"]["label"] == "Project Atlas"
    assert history["nodes"][0]["history"]["introduced_in"]["message"] == "baseline"


def test_webapp_backend_meta_handles_empty_store(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    ui = MemoryUIBackend(store_dir=store_dir, backend=backend)

    meta = ui.meta()
    health = ui.health()
    index = ui.index_status(ref="HEAD")
    rebuild = ui.index_rebuild(ref="HEAD")

    assert meta["head"] is None
    assert health["index"]["resolved_ref"] is None
    assert index["doc_count"] == 0
    assert rebuild["rebuilt"] == 0


def test_webapp_handler_exposes_operations_endpoints(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            aliases=["atlas"],
            tags=["active_priorities"],
            confidence=0.91,
        )
    )
    backend.versions.commit(graph, "baseline")

    ui_backend = MemoryUIBackend(store_dir=store_dir, backend=backend)
    handler_cls = make_handler(ui_backend)

    html_status, html_headers, html = _invoke_handler(handler_cls, path="/", method="GET")
    meta_status, meta_headers, meta_body = _invoke_handler(handler_cls, path="/api/meta", method="GET")
    index_status, _, index_body = _invoke_handler(handler_cls, path="/api/index/status?ref=HEAD", method="GET")
    rebuild_status, rebuild_headers, rebuild_body = _invoke_handler(
        handler_cls,
        path="/api/index/rebuild",
        method="POST",
        payload={"ref": "HEAD", "all_refs": False},
    )
    prune_status_code, _, prune_body = _invoke_handler(
        handler_cls, path="/api/prune/status?retention_days=7", method="GET"
    )
    audit_status, _, audit_body = _invoke_handler(handler_cls, path="/api/prune/audit?limit=10", method="GET")
    metrics_status, _, metrics_body = _invoke_handler(handler_cls, path="/api/metrics", method="GET")

    meta = json.loads(meta_body)
    index = json.loads(index_body)
    rebuild = json.loads(rebuild_body)
    prune_status = json.loads(prune_body)
    audit = json.loads(audit_body)
    metrics = json.loads(metrics_body)

    assert html_status == 200
    assert meta_status == 200
    assert index_status == 200
    assert rebuild_status == 200
    assert prune_status_code == 200
    assert audit_status == 200
    assert metrics_status == 200
    assert html_headers["X-Request-ID"]
    assert meta_headers["X-Request-ID"]
    assert rebuild_headers["X-Request-ID"]
    assert "Workspace Overview" in html
    assert meta["backend"] == "sqlite"
    assert index["persistent"] is True
    assert rebuild["rebuilt"] == 1
    assert prune_status["status"] == "ok"
    assert audit["entries"] == []
    assert metrics["requests_total"] >= 5


def test_webapp_handler_exposes_portability_endpoints(tmp_path):
    store_dir = tmp_path / ".cortex"
    ui_backend = MemoryUIBackend(store_dir=store_dir)

    def portability_scan(*, project_dir: str = "", metadata_only: bool = False):
        return {
            "status": "ok",
            "graph_path": "portable/context.json",
            "coverage": 0.5,
            "known_facts": 3,
            "total_facts": 6,
            "tools": [],
            "adoptable_sources": [],
            "metadata_only_targets": [],
            "adoptable_targets": [],
            "project_dir": project_dir,
            "metadata_only": metadata_only,
        }

    def portability_status(*, project_dir: str = ""):
        return {"status": "ok", "issues": [], "project_dir": project_dir}

    def portability_audit(*, project_dir: str = ""):
        return {"status": "ok", "issues": [], "project_dir": project_dir}

    def portability_context(
        *,
        target: str,
        project_dir: str = "",
        smart: bool | None = True,
        max_chars: int = 900,
    ):
        return {
            "status": "ok",
            "target": target,
            "project_dir": project_dir,
            "smart": smart,
            "max_chars": max_chars,
            "context_markdown": "## Shared AI Context",
        }

    def portability_sync(
        *,
        project_dir: str = "",
        targets: list[str] | None = None,
        smart: bool = True,
        policy_name: str = "full",
        max_chars: int = 1500,
    ):
        return {
            "status": "ok",
            "project_dir": project_dir,
            "targets": [{"target": "codex"}],
            "smart": smart,
            "policy_name": policy_name,
            "max_chars": max_chars,
            "fact_count": 6,
        }

    def portability_remember(
        *,
        statement: str,
        project_dir: str = "",
        targets: list[str] | None = None,
        smart: bool = True,
        policy_name: str = "full",
        max_chars: int = 1500,
    ):
        return {
            "status": "ok",
            "statement": statement,
            "project_dir": project_dir,
            "targets": [{"target": "codex"}],
            "smart": smart,
            "policy_name": policy_name,
            "max_chars": max_chars,
            "fact_count": 7,
        }

    ui_backend.portability_scan = portability_scan
    ui_backend.portability_status = portability_status
    ui_backend.portability_audit = portability_audit
    ui_backend.portability_context = portability_context
    ui_backend.portability_sync = portability_sync
    ui_backend.portability_remember = portability_remember

    handler_cls = make_handler(ui_backend)

    scan_status, _, scan_body = _invoke_handler(
        handler_cls, path="/api/portability/scan?metadata_only=true", method="GET"
    )
    status_status, _, status_body = _invoke_handler(handler_cls, path="/api/portability/status", method="GET")
    audit_status, _, audit_body = _invoke_handler(handler_cls, path="/api/portability/audit", method="GET")
    context_status, _, context_body = _invoke_handler(
        handler_cls,
        path="/api/portability/context?target=codex&smart=false&max_chars=333",
        method="GET",
    )
    sync_status, _, sync_body = _invoke_handler(
        handler_cls,
        path="/api/portability/sync",
        method="POST",
        payload={"smart": True, "max_chars": 1200},
    )
    remember_status, _, remember_body = _invoke_handler(
        handler_cls,
        path="/api/portability/remember",
        method="POST",
        payload={"statement": "We use FastAPI.", "smart": True},
    )

    scan = json.loads(scan_body)
    status = json.loads(status_body)
    audit = json.loads(audit_body)
    context = json.loads(context_body)
    sync = json.loads(sync_body)
    remember = json.loads(remember_body)

    assert scan_status == 200
    assert status_status == 200
    assert audit_status == 200
    assert context_status == 200
    assert sync_status == 200
    assert remember_status == 200
    assert scan["metadata_only"] is True
    assert status["issues"] == []
    assert audit["issues"] == []
    assert context["target"] == "codex"
    assert context["smart"] is False
    assert context["max_chars"] == 333
    assert sync["targets"][0]["target"] == "codex"
    assert sync["max_chars"] == 1200
    assert remember["statement"] == "We use FastAPI."
