import io
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from cortex.cli import main
from cortex.client import CortexClient
from cortex.graph import CortexGraph, Node
from cortex.mcp import CortexMCPServer
from cortex.server import dispatch_api_request
from cortex.service import MemoryService
from cortex.session import MemorySession
from cortex.storage import build_sqlite_backend, get_storage_backend
from cortex.storage.sqlite import sqlite_db_path
from cortex.webapp import MemoryUIBackend, make_handler


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _install_dispatching_urlopen(monkeypatch, service: MemoryService) -> None:
    def fake_urlopen(request, timeout=30.0):  # noqa: ARG001
        parsed = urllib.parse.urlparse(request.full_url)
        payload = json.loads(request.data.decode("utf-8")) if request.data else None
        headers = {key: value for key, value in request.header_items()}
        status, response = dispatch_api_request(
            service,
            method=request.get_method(),
            path=parsed.path + (f"?{parsed.query}" if parsed.query else ""),
            payload=payload,
            headers=headers,
        )
        body = json.dumps(response).encode("utf-8")
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, response.get("error", ""), hdrs=None, fp=io.BytesIO(body)
            )
        return _FakeResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _write_graph(path: Path, graph: CortexGraph) -> None:
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


def _initialize_mcp(server: CortexMCPServer) -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        }
    )
    assert response is not None
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return response


def _tool_call(server: CortexMCPServer, *, tool: str, arguments: dict | None = None, request_id: int = 2) -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
    )
    assert response is not None
    return response


def test_atlas_self_hosted_end_to_end_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_EMBEDDING_PROVIDER", "hashed")

    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    session = MemorySession(client=client, actor="agent/atlas", branch_prefix="tasks/atlas")

    seeded = session.remember_many(
        nodes=[
            {
                "id": "atlas",
                "label": "Project Atlas",
                "aliases": ["atlas"],
                "tags": ["active_priorities"],
                "confidence": 0.94,
                "brief": "User-owned memory runtime",
                "status": "planned",
            },
            {
                "id": "sdk",
                "label": "SDK",
                "aliases": ["python sdk"],
                "tags": ["infrastructure"],
                "confidence": 0.88,
                "brief": "Programmatic Cortex client",
            },
            {
                "id": "review",
                "label": "Review Gate",
                "tags": ["governance"],
                "confidence": 0.84,
                "brief": "Review before protected writes",
            },
            {
                "id": "index",
                "label": "Lexical Index",
                "aliases": ["retrieval"],
                "tags": ["infrastructure"],
                "confidence": 0.9,
                "brief": "retrieval layer for semantic memory",
            },
            {
                "id": "mcp",
                "label": "MCP Server",
                "aliases": ["mcp"],
                "tags": ["integration"],
                "confidence": 0.86,
                "brief": "Tool interface for AI clients",
            },
        ],
        message="seed atlas workspace",
    )
    sdk_edge = session.link(source_id="sdk", target_id="atlas", relation="supports")
    session.link(source_id="atlas", target_id="review", relation="guarded_by")
    session.link(source_id="atlas", target_id="index", relation="searched_by")
    session.link(source_id="atlas", target_id="mcp", relation="exposed_via")

    temporary = client.upsert_node(
        node={"id": "temporary", "label": "Temporary Insight", "tags": ["scratch"]},
        message="add temporary insight",
    )
    asserted = client.assert_claim(node_id="temporary", materialize=False, source="smoke-test")
    retracted = client.retract_claim(
        claim_id=asserted["claim"]["claim_id"],
        materialize=True,
        message="remove temporary insight",
    )

    atlas_node = client.get_node(node_id="atlas")
    atlas_lookup = client.lookup_nodes(label="atlas", limit=5)
    atlas_edge = client.get_edge(edge_id=sdk_edge["edge"]["id"])
    edge_lookup = client.lookup_edges(source_id="sdk", target_id="atlas", relation="supports", limit=5)
    claims = client.list_claims(node_id="atlas", limit=20)

    assert seeded["operation_count"] == 5
    assert temporary["node"]["label"] == "Temporary Insight"
    assert retracted["removed_node"]["label"] == "Temporary Insight"
    assert atlas_node["node"]["label"] == "Project Atlas"
    assert atlas_lookup["count"] == 1
    assert atlas_edge["edge"]["relation"] == "supports"
    assert atlas_edge["target_node"]["label"] == "Project Atlas"
    assert edge_lookup["count"] == 1
    assert claims["count"] >= 1

    search_context = session.search_context(query="atlas", limit=5)
    category = client.query_category(tag="active_priorities")
    related = client.query_related(label="Project Atlas", depth=1)
    path = client.query_path(from_label="SDK", to_label="Review Gate")
    search = client.query_search(query="retrieval", limit=5)
    dsl = client.query_dsl(query='FIND nodes WHERE tag = "infrastructure" LIMIT 10')
    nl = client.query_nl(query="how does SDK relate to Review Gate")
    health = client.health()
    meta = client.meta()

    assert "Project Atlas" in search_context["context"]
    assert category["nodes"][0]["label"] == "Project Atlas"
    assert {node["label"] for node in related["nodes"]} == {"SDK", "Review Gate", "Lexical Index", "MCP Server"}
    assert [node["label"] for node in path["paths"][0]] == ["SDK", "Project Atlas", "Review Gate"]
    assert search["results"][0]["node"]["label"] == "Lexical Index"
    assert search["embedding_enabled"] is True
    assert search["hybrid"] is True
    assert search["search_backend"] == "persistent_index"
    assert dsl["count"] >= 2
    assert nl["recognized"] is True
    assert [node["label"] for node in nl["result"]["path"]] == ["SDK", "Project Atlas", "Review Gate"]
    assert health["status"] == "ok"
    assert health["request_id"]
    assert meta["head"]

    checkout = client.checkout(ref="HEAD")
    review_graph = CortexGraph.from_v5_json(checkout["graph"])
    review_graph.add_node(
        Node(
            id="checklist",
            label="Release Checklist",
            tags=["operations"],
            confidence=0.81,
            brief="Checklist before beta release",
        )
    )
    reviewed_commit = session.commit_if_review_passes(
        graph=review_graph.export_v5(),
        message="add release checklist after review",
        against="HEAD",
    )
    checklist_search = client.query_search(query="release checklist", limit=5)

    assert reviewed_commit["status"] == "ok"
    assert reviewed_commit["review"]["status"] == "pass"
    assert checklist_search["results"][0]["node"]["label"] == "Release Checklist"

    head_commit = backend.versions.head("HEAD")
    assert head_commit is not None
    with sqlite3.connect(sqlite_db_path(store_dir)) as conn:
        conn.execute("DELETE FROM lexical_indices WHERE version_id = ?", (head_commit.version_id,))

    stale_index = client.index_status()
    rebuilt_index = client.index_rebuild(ref="HEAD")
    ready_index = client.index_status()
    atlas_search = client.query_search(query="atlas", limit=5)

    assert stale_index["stale"] is True
    assert rebuilt_index["rebuilt"] == 1
    assert ready_index["stale"] is False
    assert ready_index["last_indexed_commit"] == head_commit.version_id
    assert atlas_search["results"][0]["node"]["label"] == "Project Atlas"
    assert atlas_search["search_backend"] == "persistent_index"

    feature = session.branch_for_task("Atlas launch", prefix="feature")
    feature_branch = feature["branch_name"]
    client.upsert_node(
        node={
            "id": "atlas",
            "label": "Project Atlas",
            "aliases": ["atlas"],
            "tags": ["active_priorities"],
            "confidence": 0.94,
            "brief": "User-owned memory runtime",
            "status": "active",
            "valid_from": "2026-03-26T00:00:00Z",
        },
        message="activate atlas",
        actor="agent/atlas",
    )
    client.switch_branch(name="main")
    client.upsert_node(
        node={
            "id": "atlas",
            "label": "Project Atlas",
            "aliases": ["atlas"],
            "tags": ["active_priorities"],
            "confidence": 0.94,
            "brief": "User-owned memory runtime",
            "status": "historical",
            "valid_to": "2026-03-01T00:00:00Z",
        },
        message="archive atlas",
        actor="agent/atlas",
    )

    branches = client.list_branches()
    diff = client.diff(version_a="main", version_b=feature_branch)
    preview = client.merge_preview(other_ref=feature_branch, persist=True)
    conflicts = client.merge_conflicts()
    resolved = client.merge_resolve(conflict_id=preview["conflicts"][0]["id"], choose="incoming")
    committed_merge = client.merge_commit_resolved(message="merge atlas launch")
    merged_node = client.get_node(node_id="atlas")

    assert feature_branch in {branch["name"] for branch in branches["branches"]}
    assert any(item["node_id"] == "atlas" for item in diff["modified"])
    assert preview["pending_merge"] is True
    assert conflicts["pending"] is True
    assert resolved["remaining_conflicts"] == 0
    assert committed_merge["commit_id"]
    assert merged_node["node"]["status"] == "active"

    assert (
        main(
            [
                "governance",
                "allow",
                "protect-main",
                "--actor",
                "agent/*",
                "--action",
                "write",
                "--namespace",
                "main",
                "--require-approval",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "governance",
                "check",
                "--actor",
                "agent/atlas",
                "--action",
                "write",
                "--namespace",
                "main",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )

    with pytest.raises(RuntimeError, match="Approval required"):
        client.upsert_node(
            node={"id": "governed", "label": "Governed Write"},
            message="blocked governed write",
            actor="agent/atlas",
        )

    approved_write = client.upsert_node(
        node={"id": "governed", "label": "Governed Write"},
        message="approved governed write",
        actor="agent/atlas",
        approve=True,
    )
    assert approved_write["node"]["label"] == "Governed Write"

    ui_backend = MemoryUIBackend(store_dir=store_dir, backend=backend)
    ui_graph = CortexGraph.from_v5_json(client.checkout(ref="HEAD")["graph"])
    ui_graph.add_node(Node(id="ui-note", label="UI Note", tags=["ui"], confidence=0.7))
    ui_graph_path = tmp_path / "ui-candidate.json"
    _write_graph(ui_graph_path, ui_graph)

    ui_meta = ui_backend.meta()
    ui_health = ui_backend.health()
    ui_review = ui_backend.review(input_file=str(ui_graph_path), against="HEAD", fail_on="blocking")
    ui_blame = ui_backend.blame(input_file=None, label="atlas", ref="HEAD", limit=10)
    ui_history = ui_backend.history(input_file=None, label="atlas", ref="HEAD", limit=10)
    ui_index = ui_backend.index_status(ref="HEAD")

    assert ui_meta["backend"] == "sqlite"
    assert ui_health["status"] == "ok"
    assert ui_review["summary"]["semantic_changes"] >= 1
    assert ui_blame["nodes"][0]["node"]["label"] == "Project Atlas"
    assert ui_history["nodes"][0]["history"]["introduced_in"]
    assert ui_index["persistent"] is True

    handler_cls = make_handler(ui_backend)
    html_status, html_headers, html_body = _invoke_handler(handler_cls, path="/", method="GET")
    meta_status, meta_headers, meta_body = _invoke_handler(handler_cls, path="/api/meta", method="GET")
    health_status, health_headers, health_body = _invoke_handler(handler_cls, path="/api/health", method="GET")
    rebuild_status, rebuild_headers, rebuild_body = _invoke_handler(
        handler_cls,
        path="/api/index/rebuild",
        method="POST",
        payload={"ref": "HEAD", "all_refs": False},
    )

    assert html_status == 200
    assert "Portable AI context, without the archaeology" in html_body
    assert "Workspace Overview" in html_body
    assert html_headers["Content-Security-Policy"]
    assert html_headers["X-Request-ID"]
    assert meta_status == 200
    assert json.loads(meta_body)["current_branch"] == "main"
    assert meta_headers["X-Request-ID"]
    assert health_status == 200
    assert json.loads(health_body)["status"] == "ok"
    assert health_headers["Cache-Control"] == "no-store"
    assert rebuild_status == 200
    assert json.loads(rebuild_body)["rebuilt"] >= 0
    assert rebuild_headers["X-Request-ID"]

    mcp_server = CortexMCPServer(service=service)
    initialize = _initialize_mcp(mcp_server)
    tool_list = mcp_server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    mcp_node = _tool_call(mcp_server, tool="node_get", arguments={"node_id": "atlas"}, request_id=3)
    mcp_search = _tool_call(mcp_server, tool="query_search", arguments={"query": "atlas", "limit": 5}, request_id=4)
    mcp_index = _tool_call(mcp_server, tool="index_status", arguments={"ref": "HEAD"}, request_id=5)

    assert initialize["result"]["serverInfo"]["name"] == "Cortex"
    assert tool_list is not None
    assert any(tool["name"] == "query_search" for tool in tool_list["result"]["tools"])
    assert mcp_node["result"]["structuredContent"]["node"]["label"] == "Project Atlas"
    assert mcp_search["result"]["structuredContent"]["results"][0]["node"]["label"] == "Project Atlas"
    assert mcp_index["result"]["structuredContent"]["persistent"] is True

    with sqlite3.connect(sqlite_db_path(store_dir)) as conn:
        conn.execute(
            "INSERT INTO lexical_indices(version_id, payload, doc_count, indexed_at) VALUES(?, ?, ?, ?)",
            ("orphan", "{}", 0, "2026-03-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO embedding_indices(version_id, provider, payload, doc_count, indexed_at) VALUES(?, ?, ?, ?, ?)",
            ("orphan", "hashed", "{}", 0, "2026-03-01T00:00:00Z"),
        )

    merge_state = store_dir / "merge_state.json"
    merge_working = store_dir / "merge_working.json"
    merge_state.write_text("{}", encoding="utf-8")
    merge_working.write_text("{}", encoding="utf-8")
    stale_time = 1_700_000_000
    os.utime(merge_state, (stale_time, stale_time))
    os.utime(merge_working, (stale_time, stale_time))

    prune_status = ui_backend.prune_status(retention_days=7)
    prune_dry_run = ui_backend.prune(dry_run=True, retention_days=7)
    prune_run = ui_backend.prune(dry_run=False, retention_days=7)
    prune_audit = ui_backend.prune_audit(limit=5)
    metrics = client.metrics()
    log_lines = [json.loads(line) for line in service.observability.log_path.read_text(encoding="utf-8").splitlines()]

    assert prune_status["orphan_lexical_indices"] == 1
    assert prune_status["orphan_embedding_indices"] == 1
    assert len(prune_status["stale_merge_artifacts"]) == 2
    assert prune_dry_run["dry_run"] is True
    assert prune_run["removed_lexical_indices"] == 1
    assert prune_run["removed_embedding_indices"] == 1
    assert len(prune_run["removed_merge_artifacts"]) == 2
    assert prune_audit["entries"][0]["removed_lexical_indices"] == 1
    assert metrics["requests_total"] >= 10
    assert "/v1/query/search" in metrics["routes"]
    assert "/v1/merge-preview" in metrics["routes"]
    assert all(line["request_id"] for line in log_lines)

    (store_dir / "config.toml").write_text("[mcp]\nnamespace = 'team'\n", encoding="utf-8")
    archive = tmp_path / "atlas-backup.zip"
    restored_dir = tmp_path / "restored-store"

    assert main(["backup", "export", "--store-dir", str(store_dir), "--output", str(archive)]) == 0
    assert main(["backup", "verify", str(archive)]) == 0
    assert main(["backup", "restore", str(archive), "--store-dir", str(restored_dir)]) == 0

    restored_backend = get_storage_backend(restored_dir)
    restored_search = restored_backend.indexing.search(query="atlas", ref="HEAD", limit=5)

    assert archive.exists()
    assert restored_backend.versions.resolve_ref("HEAD")
    assert restored_search[0]["node"]["label"] == "Project Atlas"
    assert (restored_dir / "config.toml").exists()

    remote_root = tmp_path / "remote-root"
    clone_store_dir = tmp_path / "clone" / ".cortex"

    assert (
        main(
            [
                "governance",
                "allow",
                "local-sync",
                "--actor",
                "local",
                "--action",
                "push",
                "--namespace",
                "main",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert main(["remote", "add", "origin", str(remote_root), "--store-dir", str(store_dir), "--format", "json"]) == 0
    assert (
        main(
            [
                "remote",
                "push",
                "origin",
                "--branch",
                "main",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(["remote", "add", "origin", str(remote_root), "--store-dir", str(clone_store_dir), "--format", "json"])
        == 0
    )
    assert (
        main(
            [
                "remote",
                "pull",
                "origin",
                "--branch",
                "main",
                "--into-branch",
                "remotes/origin/main",
                "--store-dir",
                str(clone_store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "remote",
                "fork",
                "origin",
                "team/atlas",
                "--remote-branch",
                "main",
                "--store-dir",
                str(clone_store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )

    clone_backend = get_storage_backend(clone_store_dir)
    clone_service = MemoryService(store_dir=clone_store_dir, backend=clone_backend)
    _install_dispatching_urlopen(monkeypatch, clone_service)

    team_client = CortexClient("http://cortex.local", namespace="team")
    team_search = team_client.query_search(query="atlas", ref="team/atlas", limit=5)

    assert team_search["results"][0]["node"]["label"] == "Project Atlas"
    with pytest.raises(RuntimeError, match="outside 'team'"):
        team_client.query_search(query="atlas", ref="remotes/origin/main", limit=5)
