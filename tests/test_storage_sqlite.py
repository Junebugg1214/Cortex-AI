import json

from cortex.claims import ClaimEvent
from cortex.graph import CortexGraph, Node
from cortex.schemas.memory_v1 import RemoteRecord
from cortex.storage import build_sqlite_backend, get_storage_backend
from cortex.storage.sqlite import SQLiteStorageBackend, sqlite_db_path
from cortex.webapp import MemoryUIBackend


def _write_graph(path, graph: CortexGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_get_storage_backend_selects_sqlite_from_env(monkeypatch, tmp_path):
    store_dir = tmp_path / ".cortex"
    monkeypatch.setenv("CORTEX_STORAGE_BACKEND", "sqlite")

    backend = get_storage_backend(store_dir)

    assert isinstance(backend, SQLiteStorageBackend)
    assert sqlite_db_path(store_dir).exists()


def test_get_storage_backend_auto_detects_existing_sqlite_store(tmp_path):
    store_dir = tmp_path / ".cortex"
    build_sqlite_backend(store_dir)

    backend = get_storage_backend(store_dir)

    assert isinstance(backend, SQLiteStorageBackend)


def test_sqlite_backend_remotes_and_webapp_history_claims(tmp_path):
    local_store_dir = tmp_path / "local" / ".cortex"
    remote_root = tmp_path / "remote"
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
    context_path = tmp_path / "local" / "context.json"
    _write_graph(context_path, graph)

    backend = build_sqlite_backend(local_store_dir)
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
    backend.remotes.add_remote(RemoteRecord(name="origin", path=str(remote_root), default_branch="main"))

    push = backend.remotes.push_remote("origin", branch="main")
    clone_store_dir = tmp_path / "clone" / ".cortex"
    clone_backend = build_sqlite_backend(clone_store_dir)
    clone_backend.remotes.add_remote(RemoteRecord(name="origin", path=str(remote_root), default_branch="main"))
    pull = clone_backend.remotes.pull_remote("origin", branch="main", into_branch="imported/main")
    fork = clone_backend.remotes.fork_remote("origin", remote_branch="main", local_branch="agent/experiment")

    ui_backend = MemoryUIBackend(store_dir=local_store_dir, context_file=context_path, backend=backend)
    blame = ui_backend.blame(input_file=str(context_path), label="atlas", ref="HEAD", limit=10)
    history = ui_backend.history(input_file=str(context_path), label="atlas", ref="HEAD", limit=10)
    remotes = ui_backend.list_remotes()

    assert push["head"] == commit.version_id
    assert pull["branch"] == "imported/main"
    assert fork["forked"] is True
    assert clone_backend.versions.resolve_ref("imported/main") == commit.version_id
    assert remotes["remotes"][0]["store_path"].endswith(".cortex")
    assert blame["nodes"][0]["history"]["versions_seen"] == 1
    assert blame["nodes"][0]["claim_lineage"]["event_count"] == 1
    assert history["nodes"][0]["history"]["introduced_in"]["message"] == "baseline"
