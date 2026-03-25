import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from cortex.claims import ClaimEvent
from cortex.client import CortexClient
from cortex.graph import CortexGraph, Node
from cortex.server import dispatch_api_request
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend


def _graph_with_node(node: Node) -> CortexGraph:
    graph = CortexGraph()
    graph.add_node(node)
    return graph


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
