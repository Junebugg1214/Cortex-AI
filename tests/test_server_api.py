import io
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

import pytest

from cortex.claims import ClaimEvent
from cortex.client import CortexClient
from cortex.graph import CortexGraph, Edge, Node
from cortex.server import dispatch_api_request
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend
from cortex.storage.sqlite import sqlite_db_path


def _graph_with_node(node: Node) -> CortexGraph:
    graph = CortexGraph()
    graph.add_node(node)
    return graph


def _seed_merge_conflict(client: CortexClient) -> None:
    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], status="planned"))
    client.commit(graph=base_graph.export_v5(), message="base")

    client.create_branch(name="feature/activate")
    client.switch_branch(name="feature/activate")

    feature_graph = CortexGraph()
    feature_graph.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            status="active",
            valid_from="2026-03-01T00:00:00Z",
        )
    )
    client.commit(graph=feature_graph.export_v5(), message="activate atlas")

    client.switch_branch(name="main")
    current_graph = CortexGraph()
    current_graph.add_node(
        Node(
            id="n1",
            label="Project Atlas",
            tags=["active_priorities"],
            status="historical",
            valid_to="2026-02-01T00:00:00Z",
        )
    )
    client.commit(graph=current_graph.export_v5(), message="archive atlas")


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _install_dispatching_urlopen(monkeypatch, service: MemoryService, *, api_key: str | None = None) -> None:
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
            api_key=api_key,
        )
        body = json.dumps(response).encode("utf-8")
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, response.get("error", ""), hdrs=None, fp=io.BytesIO(body)
            )
        return _FakeResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_cortex_api_health_meta_log_and_auth(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = _graph_with_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    backend.versions.commit(graph, "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service, api_key="secret-token")

    client = CortexClient("http://cortex.local", api_key="secret-token")
    health = client.health()
    meta = client.meta()
    log = client.log(limit=5)

    assert health["status"] == "ok"
    assert health["backend"] == "sqlite"
    assert meta["current_branch"] == "main"
    assert log["versions"][0]["message"] == "baseline"

    with pytest.raises(RuntimeError, match="Unauthorized"):
        CortexClient("http://cortex.local").health()


def test_cortex_api_commit_branch_diff_and_checkout_round_trip(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    graph_a = _graph_with_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    commit_a = client.commit(graph=graph_a.export_v5(), message="main base")

    branch = client.create_branch(name="feature/atlas")
    switch = client.switch_branch(name="feature/atlas")

    graph_b = CortexGraph()
    graph_b.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    graph_b.add_node(Node(id="n2", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    commit_b = client.commit(graph=graph_b.export_v5(), message="feature add atlas")

    log = client.log(ref="feature/atlas", limit=10)
    diff = client.diff(version_a="main", version_b="feature/atlas")
    checkout = client.checkout(ref="feature/atlas")

    assert commit_a["commit"]["namespace"] == "main"
    assert branch["branch"] == "feature/atlas"
    assert switch["branch"] == "feature/atlas"
    assert commit_b["commit"]["namespace"] == "feature/atlas"
    assert log["versions"][0]["message"] == "feature add atlas"
    assert "n2" in diff["added"]
    assert "n2" in checkout["graph"]["graph"]["nodes"]


def test_cortex_api_review_blame_and_history_support_payload_graphs(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    baseline_node = Node(
        id="n1",
        canonical_id="n1",
        label="PostgreSQL",
        aliases=["postgres"],
        tags=["technical_expertise"],
        confidence=0.7,
        provenance=[{"source": "import-a", "method": "extract"}],
        status="planned",
    )
    baseline_graph = _graph_with_node(baseline_node)
    baseline_commit = backend.versions.commit(baseline_graph, "baseline")
    backend.claims.append(
        ClaimEvent.from_node(
            baseline_node,
            op="assert",
            source="import-a",
            method="extract",
            version_id=baseline_commit.version_id,
            timestamp="2026-03-23T00:00:00Z",
        )
    )

    current_node = Node(
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
    current_graph = _graph_with_node(current_node)

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    review = client.review(against="HEAD", graph=current_graph.export_v5())
    blame = client.blame(label="postgres", graph=current_graph.export_v5(), ref="HEAD", limit=10)
    history = client.history(label="postgres", graph=current_graph.export_v5(), ref="HEAD", limit=10)

    assert review["summary"]["semantic_changes"] >= 1
    assert any(change["type"] == "lifecycle_shift" for change in review["semantic_changes"])
    assert blame["nodes"][0]["history"]["versions_seen"] == 1
    assert blame["nodes"][0]["claim_lineage"]["event_count"] == 1
    assert history["nodes"][0]["history"]["introduced_in"]["message"] == "baseline"


def test_cortex_api_query_endpoints_support_ref_backed_queries(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.82))
    graph.add_node(
        Node(
            id="n2",
            label="Project Atlas",
            aliases=["atlas"],
            tags=["active_priorities"],
            confidence=0.93,
            brief="Local memory infrastructure",
        )
    )
    graph.add_node(
        Node(
            id="n3",
            label="SDK",
            aliases=["python sdk"],
            tags=["infrastructure"],
            confidence=0.75,
            brief="Python SDK for Cortex",
        )
    )
    graph.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="supports"))
    graph.add_edge(Edge(id="e2", source_id="n2", target_id="n3", relation="requires"))
    backend.versions.commit(graph, "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    category = client.query_category(tag="active_priorities")
    path = client.query_path(from_label="Python", to_label="SDK")
    related = client.query_related(label="Project Atlas", depth=1)
    search = client.query_search(query="atlas", limit=5)
    dsl = client.query_dsl(query='FIND nodes WHERE tag = "active_priorities" LIMIT 5')
    nl = client.query_nl(query="how does Python relate to SDK")

    assert category["count"] == 1
    assert category["nodes"][0]["label"] == "Project Atlas"
    assert category["graph_source"]
    assert path["found"] is True
    assert [node["label"] for node in path["paths"][0]] == ["Python", "Project Atlas", "SDK"]
    assert [node["label"] for node in related["nodes"]] == ["Python", "SDK"]
    assert search["results"][0]["node"]["label"] == "Project Atlas"
    assert search["count"] >= 1
    assert search["search_backend"] == "persistent_index"
    assert search["persistent_index"] is True
    assert dsl["type"] == "find"
    assert dsl["count"] == 1
    assert nl["recognized"] is True
    assert [node["label"] for node in nl["result"]["path"]] == ["Python", "Project Atlas", "SDK"]


def test_cortex_api_query_endpoints_support_payload_graphs(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    baseline = CortexGraph()
    baseline.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    backend.versions.commit(baseline, "baseline")

    payload_graph = CortexGraph()
    payload_graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    payload_graph.add_node(
        Node(
            id="n2",
            label="Embedding Index",
            aliases=["vector index"],
            tags=["infrastructure"],
            confidence=0.86,
            brief="Hybrid retrieval index",
        )
    )
    payload_graph.add_edge(Edge(id="e1", source_id="n1", target_id="n2", relation="uses"))

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    payload_search = client.query_search(query="vector index", graph=payload_graph.export_v5(), limit=5)
    payload_path = client.query_path(
        from_label="Project Atlas",
        to_label="Embedding Index",
        graph=payload_graph.export_v5(),
    )
    unknown_nl = client.query_nl(query="tell me something unexpected", graph=payload_graph.export_v5())

    assert payload_search["graph_source"] == "payload"
    assert payload_search["results"][0]["node"]["label"] == "Embedding Index"
    assert payload_search["search_backend"] == "payload_graph"
    assert payload_search["persistent_index"] is False
    assert payload_path["graph_source"] == "payload"
    assert payload_path["found"] is True
    assert [node["label"] for node in payload_path["paths"][0]] == ["Project Atlas", "Embedding Index"]
    assert unknown_nl["recognized"] is False
    assert "Query not recognized" in unknown_nl["message"]


def test_cortex_api_index_status_and_rebuild_surface(tmp_path, monkeypatch):
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
            brief="Local memory infrastructure",
        )
    )
    commit = backend.versions.commit(graph, "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    with sqlite3.connect(sqlite_db_path(store_dir)) as conn:
        conn.execute("DELETE FROM lexical_indices WHERE version_id = ?", (commit.version_id,))

    client = CortexClient("http://cortex.local")
    stale = client.index_status()
    rebuilt = client.index_rebuild(ref="HEAD")
    ready = client.index_status()
    search = client.query_search(query="atlas", limit=5)

    assert stale["persistent"] is True
    assert stale["stale"] is True
    assert rebuilt["rebuilt"] == 1
    assert rebuilt["last_indexed_commit"] == commit.version_id
    assert ready["stale"] is False
    assert ready["last_indexed_commit"] == commit.version_id
    assert search["search_backend"] == "persistent_index"
    assert search["results"][0]["node"]["label"] == "Project Atlas"


def test_cortex_api_query_dsl_returns_client_error_for_invalid_queries(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="n1", label="Python")), "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    with pytest.raises(RuntimeError, match="Unknown statement type"):
        client.query_dsl(query="BOGUS QUERY")


def test_cortex_api_detects_and_resolves_memory_conflicts(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    conflict_graph = _graph_with_node(
        Node(id="n1", label="Rust", tags=["technical_expertise", "negations"], confidence=0.8)
    )
    backend.versions.commit(conflict_graph, "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    detected = client.detect_conflicts(ref="HEAD")
    assert detected["count"] == 1
    assert detected["conflicts"][0]["type"] == "negation_conflict"

    resolved = client.resolve_conflict(
        conflict_id=detected["conflicts"][0]["id"],
        action="keep-old",
        graph=conflict_graph.export_v5(),
    )
    resolved_graph = CortexGraph.from_v5_json(resolved["graph"])

    assert resolved["remaining_conflicts"] == 0
    assert "negations" not in resolved_graph.nodes["n1"].tags


def test_cortex_api_merge_preview_resolve_and_commit_flow(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    _seed_merge_conflict(client)

    preview = client.merge_preview(other_ref="feature/activate", persist=True)
    assert preview["ok"] is False
    assert preview["pending_merge"] is True
    conflict_id = preview["conflicts"][0]["id"]

    conflicts = client.merge_conflicts()
    assert conflicts["pending"] is True
    assert conflicts["conflicts"][0]["id"] == conflict_id

    resolved = client.merge_resolve(conflict_id=conflict_id, choose="incoming")
    resolved_graph = CortexGraph.from_v5_json(resolved["graph"])
    assert resolved["pending"] is True
    assert resolved["remaining_conflicts"] == 0
    assert not resolved["conflicts"]
    assert resolved_graph.nodes["n1"].status == "active"

    committed = client.merge_commit_resolved()
    assert committed["commit_id"]
    head = backend.versions.head("main")
    assert head is not None
    assert head.source == "merge"
    merged_graph = backend.versions.checkout(head.version_id)
    assert merged_graph.nodes["n1"].status == "active"

    conflicts_after = client.merge_conflicts()
    assert conflicts_after["pending"] is False


def test_cortex_api_merge_abort_clears_pending_state(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    _seed_merge_conflict(client)

    preview = client.merge_preview(other_ref="feature/activate", persist=True)
    assert preview["pending_merge"] is True

    aborted = client.merge_abort()
    assert aborted["aborted"] is True
    assert aborted["pending"] is False
    assert aborted["other_ref"] == "feature/activate"

    conflicts_after = client.merge_conflicts()
    assert conflicts_after["pending"] is False
