import io
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

import pytest

from cortex.claims import ClaimEvent
from cortex.client import CortexClient
from cortex.config import APIKeyConfig
from cortex.graph import CortexGraph, Edge, Node
from cortex.http_hardening import HTTPRequestPolicy
from cortex.server import dispatch_api_request, make_api_handler
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


def _invoke_api_handler(
    handler_cls,
    *,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.command = method
    handler.request_version = "HTTP/1.1"
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.client_address = ("127.0.0.1", 8766)
    resolved_headers = {
        "Content-Length": str(len(raw)),
        "Host": "127.0.0.1:8766",
    }
    if method == "POST":
        resolved_headers["Content-Type"] = "application/json"
    if headers:
        resolved_headers.update(headers)
    handler.headers = resolved_headers
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
    return handler._status, handler._headers, handler.wfile.getvalue().decode("utf-8")


def _install_dispatching_urlopen(
    monkeypatch,
    service: MemoryService,
    *,
    api_key: str | None = None,
    auth_keys: tuple[APIKeyConfig, ...] = (),
) -> None:
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
            auth_keys=auth_keys,
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
    assert health["release"]["project_version"] == client.sdk_info()["version"]
    assert meta["current_branch"] == "main"
    assert meta["release"]["contract"]["hash"] == health["release"]["contract"]["hash"]
    assert log["versions"][0]["message"] == "baseline"

    with pytest.raises(RuntimeError, match="Unauthorized"):
        CortexClient("http://cortex.local").health()


def test_cortex_api_accepts_case_insensitive_bearer_auth(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="n1", label="Project Atlas")), "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    status, response = dispatch_api_request(
        service,
        method="GET",
        path="/v1/health",
        headers={"Authorization": "bearer scoped-token"},
        auth_keys=(APIKeyConfig(name="reader", token="scoped-token", scopes=("read",), namespaces=("*",)),),
    )

    assert status == 200
    assert response["status"] == "ok"


def test_cortex_api_handler_rejects_non_json_post_content_type(tmp_path):
    store_dir = tmp_path / ".cortex"
    service = MemoryService(store_dir=store_dir)
    handler_cls = make_api_handler(service)

    status, _, body = _invoke_api_handler(
        handler_cls,
        path="/v1/review",
        method="POST",
        payload={"against": "HEAD"},
        headers={"Content-Type": "text/plain"},
    )

    assert status == 415
    assert "application/json" in json.loads(body)["error"]


def test_cortex_api_handler_rejects_oversized_json_body(tmp_path):
    store_dir = tmp_path / ".cortex"
    service = MemoryService(store_dir=store_dir)
    handler_cls = make_api_handler(service, request_policy=HTTPRequestPolicy(max_body_bytes=8))

    status, _, body = _invoke_api_handler(
        handler_cls,
        path="/v1/review",
        method="POST",
        payload={"against": "HEAD"},
    )

    assert status == 413
    assert "exceeds 8 bytes" in json.loads(body)["error"]


def test_cortex_api_handler_rate_limits_hosted_requests(tmp_path):
    store_dir = tmp_path / ".cortex"
    service = MemoryService(store_dir=store_dir)
    handler_cls = make_api_handler(service, request_policy=HTTPRequestPolicy(rate_limit_per_minute=1))

    first_status, _, first_body = _invoke_api_handler(handler_cls, path="/v1/health", method="GET")
    second_status, _, second_body = _invoke_api_handler(handler_cls, path="/v1/health", method="GET")

    assert first_status == 200
    assert json.loads(first_body)["status"] == "ok"
    assert second_status == 429
    assert "Too many requests" in json.loads(second_body)["error"]


def test_cortex_api_metrics_request_ids_and_structured_logs(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="n1", label="Project Atlas", aliases=["atlas"])), "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    health = client.health()
    search = client.query_search(query="atlas", limit=5)
    metrics = client.metrics()

    lines = [json.loads(line) for line in service.observability.log_path.read_text(encoding="utf-8").splitlines()]

    assert health["request_id"]
    assert search["request_id"]
    assert metrics["requests_total"] >= 2
    assert metrics["release"]["project_version"] == service.release()["project_version"]
    assert "/v1/health" in metrics["routes"]
    assert "/v1/query/search" in metrics["routes"]
    assert metrics["index"]["lag_commits"] == 0
    assert lines[-1]["path"] == "/v1/metrics"
    assert all(line["request_id"] for line in lines)


def test_cortex_client_reports_network_errors_cleanly():
    client = CortexClient("http://cortex.local")

    def fail_urlopen(request, timeout=30.0):  # noqa: ARG001
        raise urllib.error.URLError("connection refused")

    original = urllib.request.urlopen
    urllib.request.urlopen = fail_urlopen
    try:
        with pytest.raises(RuntimeError, match="Network error while calling Cortex: connection refused"):
            client.health()
    finally:
        urllib.request.urlopen = original


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


def test_cortex_api_object_node_and_edge_surface(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    atlas = client.upsert_node(
        node={
            "label": "Project Atlas",
            "aliases": ["atlas"],
            "tags": ["active_priorities"],
            "confidence": 0.92,
        },
        message="add atlas",
    )
    sdk = client.upsert_node(
        node={
            "id": "sdk",
            "label": "Python SDK",
            "tags": ["infrastructure"],
            "confidence": 0.83,
        },
        message="add sdk",
    )
    edge = client.upsert_edge(
        edge={
            "source_id": atlas["node"]["id"],
            "target_id": sdk["node"]["id"],
            "relation": "depends_on",
            "confidence": 0.75,
        },
        message="link atlas sdk",
    )

    node_detail = client.get_node(atlas["node"]["id"])
    edge_detail = client.get_edge(edge["edge"]["id"])
    node_lookup = client.lookup_nodes(label="atlas", limit=5)
    edge_lookup = client.lookup_edges(
        source_id=atlas["node"]["id"],
        target_id=sdk["node"]["id"],
        relation="depends_on",
        limit=5,
    )
    deleted_edge = client.delete_edge(edge_id=edge["edge"]["id"], message="unlink atlas sdk")

    assert atlas["commit"]["version_id"]
    assert atlas["claim"]["op"] == "assert"
    assert node_detail["node"]["label"] == "Project Atlas"
    assert node_detail["claim_lineage"]["event_count"] >= 1
    assert edge_detail["source_node"]["label"] == "Project Atlas"
    assert edge_detail["target_node"]["label"] == "Python SDK"
    assert node_lookup["count"] == 1
    assert edge_lookup["count"] == 1
    assert deleted_edge["edge"]["relation"] == "depends_on"


def test_cortex_api_namespace_isolation_filters_and_blocks_cross_namespace(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    main_graph = _graph_with_node(Node(id="n1", label="Main Atlas", aliases=["atlas-main"], confidence=0.8))
    backend.versions.commit(main_graph, "main base")
    backend.versions.create_branch("team/atlas", switch=True)

    team_graph = _graph_with_node(Node(id="n2", label="Team Atlas", aliases=["atlas-team"], confidence=0.9))
    backend.versions.commit(team_graph, "team base")
    backend.versions.switch_branch("main")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local", namespace="team")
    branches = client.list_branches()
    team_search = client.query_search(query="atlas-team", ref="team/atlas", limit=5)

    assert [branch["name"] for branch in branches["branches"]] == ["team/atlas"]
    assert team_search["results"][0]["node"]["label"] == "Team Atlas"

    with pytest.raises(RuntimeError, match="outside 'team'"):
        client.query_search(query="atlas-main", ref="main", limit=5)

    with pytest.raises(RuntimeError, match="outside namespace"):
        client.create_branch(name="ops/infra")

    with pytest.raises(RuntimeError, match="outside namespace"):
        client.upsert_node(node={"label": "Leaked Node"})


def test_cortex_api_scoped_keys_enforce_scope_and_namespace(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    backend.versions.commit(_graph_with_node(Node(id="n1", label="Main Atlas", aliases=["atlas-main"])), "main base")
    backend.versions.create_branch("team/atlas", switch=True)
    backend.versions.commit(_graph_with_node(Node(id="n2", label="Team Atlas", aliases=["atlas-team"])), "team base")
    backend.versions.switch_branch("main")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(
        monkeypatch,
        service,
        auth_keys=(
            APIKeyConfig(name="reader", token="reader-token", scopes=("read",), namespaces=("team",)),
            APIKeyConfig(name="writer", token="writer-token", scopes=("write",), namespaces=("team",)),
        ),
    )

    reader = CortexClient("http://cortex.local", api_key="reader-token")
    allowed = reader.query_search(query="atlas-team", ref="team/atlas", limit=5)

    assert allowed["results"][0]["node"]["label"] == "Team Atlas"

    with pytest.raises(RuntimeError, match="scope 'write'"):
        reader.upsert_node(node={"label": "Denied Write"})

    wrong_namespace = CortexClient("http://cortex.local", api_key="reader-token", namespace="main")
    with pytest.raises(RuntimeError, match="outside API key 'reader' namespace scope"):
        wrong_namespace.query_search(query="atlas-team", ref="team/atlas", limit=5)


def test_cortex_api_claim_assert_retract_and_materialize(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    created = client.upsert_node(
        node={
            "id": "atlas",
            "label": "Project Atlas",
            "aliases": ["atlas"],
            "tags": ["active_priorities"],
        },
        message="seed atlas",
        record_claim=False,
    )
    asserted = client.assert_claim(node_id="atlas", materialize=False, source="manual-source")
    retracted = client.retract_claim(claim_id=asserted["claim"]["claim_id"], materialize=True, message="retract atlas")
    remaining = client.lookup_nodes(node_id="atlas")
    claims = client.list_claims(node_id="atlas", limit=10)

    assert created["node"]["id"] == "atlas"
    assert asserted["commit"] is None
    assert asserted["claim"]["op"] == "assert"
    assert retracted["claim"]["op"] == "retract"
    assert retracted["removed_node"]["label"] == "Project Atlas"
    assert remaining["count"] == 0
    assert claims["claims"][0]["op"] == "retract"


def test_cortex_api_memory_batch_materializes_object_operations(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    batch = client.memory_batch(
        operations=[
            {
                "op": "upsert_node",
                "node": {
                    "id": "atlas",
                    "label": "Project Atlas",
                    "aliases": ["atlas"],
                    "tags": ["active_priorities"],
                },
            },
            {
                "op": "upsert_node",
                "node": {
                    "id": "sdk",
                    "label": "Python SDK",
                    "tags": ["infrastructure"],
                    "brief": "SDK surface for Cortex",
                },
            },
            {
                "op": "upsert_edge",
                "edge": {
                    "source_id": "atlas",
                    "target_id": "sdk",
                    "relation": "requires",
                },
            },
            {
                "op": "assert_claim",
                "node_id": "sdk",
                "materialize": False,
                "source": "batch-source",
            },
        ],
        message="batch object write",
    )
    query = client.query_search(query="python sdk", limit=5)
    edge_lookup = client.lookup_edges(source_id="atlas", target_id="sdk", relation="requires", limit=5)

    assert batch["commit"]["version_id"]
    assert batch["operation_count"] == 4
    assert len(batch["claims"]) == 3
    assert query["results"][0]["node"]["label"] == "Python SDK"
    assert edge_lookup["count"] == 1


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


def test_cortex_api_query_search_uses_optional_embeddings_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_EMBEDDING_PROVIDER", "hashed")
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    graph = CortexGraph()
    graph.add_node(
        Node(
            id="n1",
            label="Index Core",
            tags=["infrastructure"],
            confidence=0.9,
            brief="retrievel layer for semantic memory",
        )
    )
    backend.versions.commit(graph, "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    client = CortexClient("http://cortex.local")
    search = client.query_search(query="retrieval", limit=5)

    assert search["embedding_enabled"] is True
    assert search["embedding_provider"] == "hashed"
    assert search["hybrid"] is True
    assert search["results"][0]["node"]["label"] == "Index Core"
    assert "embedding" in search["results"][0]["sources"]


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


def test_cortex_api_prune_supports_dry_run_and_audit(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="n1", label="Project Atlas", aliases=["atlas"])), "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

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

    client = CortexClient("http://cortex.local")
    status = client.prune_status(retention_days=7)
    dry_run = client.prune(dry_run=True, retention_days=7)
    assert merge_state.exists() and merge_working.exists()
    pruned = client.prune(dry_run=False, retention_days=7)
    audit = client.prune_audit(limit=5)

    assert status["orphan_lexical_indices"] == 1
    assert status["orphan_embedding_indices"] == 1
    assert len(status["stale_merge_artifacts"]) == 2
    assert dry_run["dry_run"] is True
    assert pruned["removed_lexical_indices"] == 1
    assert pruned["removed_embedding_indices"] == 1
    assert len(pruned["removed_merge_artifacts"]) == 2
    assert not merge_state.exists() and not merge_working.exists()
    assert audit["entries"][0]["removed_lexical_indices"] == 1


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
