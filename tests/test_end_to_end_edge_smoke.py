import io
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

import pytest

from cortex.cli import main
from cortex.client import CortexClient
from cortex.config import load_selfhost_config
from cortex.graph.graph import CortexGraph, Node
from cortex.mcp.mcp import CortexMCPServer
from cortex.mcp.mcp import main as mcp_main
from cortex.service.server import dispatch_api_request
from cortex.service.server import main as server_main
from cortex.service.service import MemoryService
from cortex.service.webapp import MemoryUIBackend
from cortex.storage import build_sqlite_backend, get_storage_backend
from cortex.storage.sqlite import sqlite_db_path


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _install_dispatching_urlopen(monkeypatch, service: MemoryService, *, auth_keys=()) -> None:
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
            auth_keys=auth_keys,
        )
        body = json.dumps(response).encode("utf-8")
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, response.get("error", ""), hdrs=None, fp=io.BytesIO(body)
            )
        return _FakeResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _initialize(server: CortexMCPServer) -> dict:
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


def test_regulated_team_edge_case_second_pass(tmp_path, monkeypatch, capsys):
    config_dir = tmp_path / "ops"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    config_path.write_text(
        """
[runtime]
store_dir = "store"

[server]
host = "127.0.0.1"
port = 8766

[mcp]
namespace = "team"

[[auth.keys]]
name = "reader"
token = "reader-token"
scopes = ["read"]
namespaces = ["team"]

[[auth.keys]]
name = "writer"
token = "writer-token"
scopes = ["read", "write", "branch", "merge", "index"]
namespaces = ["team"]

[[auth.keys]]
name = "maintainer"
token = "maintainer-token"
scopes = ["admin"]
namespaces = ["*"]
""".strip(),
        encoding="utf-8",
    )

    config = load_selfhost_config(config_path=config_path, env={})
    store_dir = config.store_dir
    backend = build_sqlite_backend(store_dir)

    main_graph = CortexGraph()
    main_graph.add_node(Node(id="public", label="Public Atlas", aliases=["public-atlas"], confidence=0.7))
    backend.versions.commit(main_graph, "seed main")
    backend.versions.create_branch("team/incidents", switch=True)

    team_graph = CortexGraph()
    team_graph.add_node(
        Node(
            id="incident",
            label="Incident Atlas",
            aliases=["incident-atlas"],
            tags=["incident", "restricted"],
            confidence=0.91,
            brief="Restricted incident memory",
            status="planned",
        )
    )
    backend.versions.commit(team_graph, "seed incident workspace")
    backend.versions.switch_branch("main")

    (store_dir / "config.toml").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service, auth_keys=config.api_keys)

    assert server_main(["--config", str(config_path), "--check"]) == 0
    server_output = capsys.readouterr().out
    assert "Cortex server diagnostics:" in server_output
    assert "reader" in server_output
    assert "writer" in server_output
    assert "reader-token" not in server_output

    assert mcp_main(["--config", str(config_path), "--check"]) == 0
    mcp_output = capsys.readouterr().out
    assert "Cortex mcp diagnostics:" in mcp_output
    assert "Namespace: team" in mcp_output

    reader = CortexClient("http://cortex.local", api_key="reader-token")
    writer = CortexClient("http://cortex.local", api_key="writer-token", namespace="team")
    maintainer = CortexClient("http://cortex.local", api_key="maintainer-token")

    reader_health = reader.health()
    reader_team_search = reader.query_search(query="incident-atlas", ref="team/incidents", limit=5)

    assert reader_health["status"] == "ok"
    assert reader_team_search["results"][0]["node"]["label"] == "Incident Atlas"

    with pytest.raises(RuntimeError, match="outside 'team'"):
        reader.query_search(query="public-atlas", ref="main", limit=5)

    with pytest.raises(RuntimeError, match="scope 'write'"):
        reader.upsert_node(node={"label": "Denied Reader Write"})

    with pytest.raises(RuntimeError, match="scope 'index'"):
        reader.index_status(ref="team/incidents")

    branches_before = writer.list_branches()
    feature = writer.create_branch(
        name="team/incidents/triage",
        from_ref="team/incidents",
        switch=True,
        actor="agent/team",
    )
    writer.upsert_node(
        node={
            "id": "incident",
            "label": "Incident Atlas",
            "aliases": ["incident-atlas"],
            "tags": ["incident", "restricted"],
            "confidence": 0.91,
            "brief": "Restricted incident memory",
            "status": "active",
            "valid_from": "2026-03-26T00:00:00Z",
        },
        message="activate incident",
        actor="agent/team",
    )
    writer.switch_branch(name="team/incidents", actor="agent/team")
    writer.upsert_node(
        node={
            "id": "incident",
            "label": "Incident Atlas",
            "aliases": ["incident-atlas"],
            "tags": ["incident", "restricted"],
            "confidence": 0.91,
            "brief": "Restricted incident memory",
            "status": "historical",
            "valid_to": "2026-03-20T00:00:00Z",
        },
        message="archive incident",
        actor="agent/team",
    )

    branches_after = writer.list_branches()
    preview = writer.merge_preview(other_ref=feature["branch"], persist=True)
    pending = writer.merge_conflicts()
    aborted = writer.merge_abort()
    conflicts_after_abort = writer.merge_conflicts()

    assert [branch["name"] for branch in branches_before["branches"]] == ["team/incidents"]
    assert feature["branch"] == "team/incidents/triage"
    assert {branch["name"] for branch in branches_after["branches"]} == {"team/incidents", "team/incidents/triage"}
    assert preview["pending_merge"] is True
    assert pending["pending"] is True
    assert aborted["aborted"] is True
    assert conflicts_after_abort["pending"] is False

    with pytest.raises(RuntimeError, match="outside namespace"):
        writer.create_branch(name="ops/forbidden", from_ref="team/incidents")

    conflict_graph = CortexGraph()
    conflict_graph.add_node(
        Node(
            id="negated",
            label="Unstable Fact",
            tags=["incident", "technical_expertise", "negations"],
            confidence=0.73,
        )
    )
    detected = writer.detect_conflicts(graph=conflict_graph.export_v5())
    resolved = writer.resolve_conflict(
        conflict_id=detected["conflicts"][0]["id"],
        action="keep-old",
        graph=conflict_graph.export_v5(),
    )

    assert detected["count"] == 1
    assert detected["conflicts"][0]["type"] == "negation_conflict"
    assert resolved["remaining_conflicts"] == 0

    assert (
        main(
            [
                "governance",
                "allow",
                "protect-team",
                "--actor",
                "agent/*",
                "--action",
                "write",
                "--namespace",
                "team/*",
                "--require-approval",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()

    with pytest.raises(RuntimeError, match="Approval required"):
        writer.upsert_node(
            node={"id": "restricted-note", "label": "Restricted Note"},
            message="blocked team write",
            actor="agent/team",
        )

    approved = writer.upsert_node(
        node={"id": "restricted-note", "label": "Restricted Note"},
        message="approved team write",
        actor="agent/team",
        approve=True,
    )
    team_index = writer.index_status(ref="team/incidents")
    rebuilt = writer.index_rebuild(ref="team/incidents")

    assert approved["node"]["label"] == "Restricted Note"
    assert team_index["persistent"] is True
    assert rebuilt["status"] == "ok"

    ui = MemoryUIBackend(store_dir=store_dir, backend=backend)
    blame = ui.blame(input_file=None, label="incident-atlas", ref="team/incidents", limit=10)
    history = ui.history(input_file=None, label="incident-atlas", ref="team/incidents", limit=10)

    assert blame["nodes"][0]["node"]["label"] == "Incident Atlas"
    assert blame["nodes"][0]["claim_lineage"]["event_count"] >= 1
    assert history["nodes"][0]["history"]["versions_seen"] >= 1

    mcp_server = CortexMCPServer(service=service, namespace="team")
    initialize = _initialize(mcp_server)
    team_allowed = _tool_call(
        mcp_server,
        tool="query_search",
        arguments={"query": "incident-atlas", "ref": "team/incidents", "limit": 5},
        request_id=2,
    )
    team_blocked = _tool_call(
        mcp_server,
        tool="query_search",
        arguments={"query": "public-atlas", "ref": "main", "limit": 5},
        request_id=3,
    )

    assert initialize["result"]["serverInfo"]["name"] == "Cortex"
    assert team_allowed["result"]["structuredContent"]["results"][0]["node"]["label"] == "Incident Atlas"
    assert team_blocked["result"]["isError"] is True

    with sqlite3.connect(sqlite_db_path(store_dir)) as conn:
        conn.execute(
            "INSERT INTO lexical_indices(version_id, payload, doc_count, indexed_at) VALUES(?, ?, ?, ?)",
            ("orphan", "{}", 0, "2026-03-01T00:00:00Z"),
        )

    merge_state = store_dir / "merge_state.json"
    merge_working = store_dir / "merge_working.json"
    merge_state.write_text("{}", encoding="utf-8")
    merge_working.write_text("{}", encoding="utf-8")
    stale_time = 1_700_000_000
    os.utime(merge_state, (stale_time, stale_time))
    os.utime(merge_working, (stale_time, stale_time))

    prune_status = maintainer.prune_status(retention_days=7)
    prune_dry_run = maintainer.prune(dry_run=True, retention_days=7)
    pruned = maintainer.prune(dry_run=False, retention_days=7)
    prune_audit = maintainer.prune_audit(limit=5)
    metrics = maintainer.metrics()

    assert prune_status["orphan_lexical_indices"] == 1
    assert prune_dry_run["dry_run"] is True
    assert pruned["removed_lexical_indices"] == 1
    assert len(pruned["removed_merge_artifacts"]) == 2
    assert prune_audit["entries"][0]["removed_lexical_indices"] == 1
    assert metrics["requests_total"] >= 1

    archive = tmp_path / "team-backup.zip"
    restored_dir = tmp_path / "restored-team-store"

    assert main(["backup", "export", "--store-dir", str(store_dir), "--output", str(archive)]) == 0
    assert main(["backup", "verify", str(archive)]) == 0
    assert main(["backup", "restore", str(archive), "--store-dir", str(restored_dir)]) == 0
    capsys.readouterr()

    restored_backend = get_storage_backend(restored_dir)
    restored_search = restored_backend.indexing.search(query="incident-atlas", ref="team/incidents", limit=5)

    assert archive.exists()
    assert restored_search[0]["node"]["label"] == "Incident Atlas"
    assert (restored_dir / "config.toml").exists()
