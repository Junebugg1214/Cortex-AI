import io
import json
import urllib.error
import urllib.parse
import urllib.request

from cortex.client import CortexClient
from cortex.graph import CortexGraph, Node
from cortex.server import dispatch_api_request
from cortex.service import MemoryService
from cortex.session import MemorySession, branch_name_for_task, render_search_context
from cortex.storage import build_sqlite_backend


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


def test_branch_name_for_task_and_context_renderer():
    branch_name = branch_name_for_task("Draft Atlas Launch!", prefix="tasks/app")
    context = render_search_context(
        {
            "query": "atlas",
            "results": [
                {
                    "node": {
                        "label": "Project Atlas",
                        "brief": "Local-first memory runtime",
                        "tags": ["active_priorities"],
                        "aliases": ["atlas"],
                    },
                    "score": 0.98,
                }
            ],
        },
        max_items=5,
        max_chars=200,
        include_scores=True,
    )

    assert branch_name == "tasks/app/draft-atlas-launch"
    assert "Project Atlas" in context
    assert "score 0.980" in context
    assert "active_priorities" in context


def test_memory_session_remember_many_search_context_and_branching(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    session = MemorySession(CortexClient("http://cortex.local"), actor="agent/app")
    batch = session.remember_many(
        nodes=[
            {
                "id": "atlas",
                "label": "Project Atlas",
                "brief": "Local-first memory runtime",
                "aliases": ["atlas"],
                "tags": ["active_priorities"],
                "confidence": 0.94,
            },
            {
                "id": "sdk",
                "label": "Python SDK",
                "brief": "Programmatic Cortex client",
                "tags": ["infrastructure"],
                "confidence": 0.88,
            },
        ],
        message="seed adoption examples",
    )
    link = session.link(source_id="atlas", target_id="sdk", relation="depends_on")
    search = session.search_context(query="atlas", limit=5)
    branch = session.branch_for_task("Atlas rollout", prefix="tasks/app")

    assert batch["operation_count"] == 2
    assert link["edge"]["relation"] == "depends_on"
    assert search["count"] >= 1
    assert "Project Atlas" in search["context"]
    assert branch["branch_name"] == "tasks/app/atlas-rollout"


def test_memory_session_commit_if_review_passes(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    baseline = CortexGraph()
    baseline.add_node(Node(id="atlas", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    backend.versions.commit(baseline, "baseline")

    service = MemoryService(store_dir=store_dir, backend=backend)
    _install_dispatching_urlopen(monkeypatch, service)

    session = MemorySession(CortexClient("http://cortex.local"), actor="agent/app")
    updated = CortexGraph.from_v5_json(baseline.export_v5())
    updated.add_node(Node(id="sdk", label="Python SDK", tags=["infrastructure"], confidence=0.84))
    result = session.commit_if_review_passes(
        graph=updated.export_v5(),
        message="add sdk after review",
        against="HEAD",
    )

    assert result["status"] == "ok"
    assert result["review"]["status"] == "pass"
    assert result["commit"]["message"] == "add sdk after review"
