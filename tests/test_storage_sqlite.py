import json
import sqlite3

from cortex.graph.claims import ClaimEvent
from cortex.graph.graph import CortexGraph, Node
from cortex.schemas.memory_v1 import RemoteRecord
from cortex.service.webapp import MemoryUIBackend
from cortex.storage import build_sqlite_backend, get_storage_backend
from cortex.storage.sqlite import SQLiteStorageBackend, sqlite_db_path


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


def test_sqlite_persistent_index_survives_backend_restart(tmp_path):
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

    status = backend.indexing.status(ref="HEAD")
    first_results = backend.indexing.search(query="atlas", ref="HEAD", limit=5)
    restarted = build_sqlite_backend(store_dir)
    restarted_status = restarted.indexing.status(ref="HEAD")
    restarted_results = restarted.indexing.search(query="atlas", ref="HEAD", limit=5)

    with sqlite3.connect(sqlite_db_path(store_dir)) as conn:
        row = conn.execute("SELECT COUNT(*) FROM lexical_indices WHERE version_id = ?", (commit.version_id,)).fetchone()

    assert status["persistent"] is True
    assert status["stale"] is False
    assert status["last_indexed_commit"] == commit.version_id
    assert restarted_status["stale"] is False
    assert restarted_status["last_indexed_commit"] == commit.version_id
    assert first_results[0]["node"]["label"] == "Project Atlas"
    assert restarted_results[0]["node"]["label"] == "Project Atlas"
    assert row is not None and row[0] == 1


def test_sqlite_index_rebuilds_all_refs_and_matches_graph_search(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    baseline = CortexGraph()
    baseline.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.82))
    baseline.add_node(
        Node(
            id="n2",
            label="Project Atlas",
            aliases=["atlas"],
            tags=["active_priorities"],
            confidence=0.93,
            brief="Local memory infrastructure",
        )
    )
    first_commit = backend.versions.commit(baseline, "baseline")
    backend.versions.create_branch("feature/sdk", switch=True)

    feature = CortexGraph.from_v5_json(baseline.export_v5())
    feature.add_node(
        Node(
            id="n3",
            label="SDK",
            aliases=["python sdk"],
            tags=["infrastructure"],
            confidence=0.75,
            brief="Python SDK for Cortex",
        )
    )
    second_commit = backend.versions.commit(feature, "add sdk")
    backend.versions.switch_branch("main")

    with sqlite3.connect(sqlite_db_path(store_dir)) as conn:
        conn.execute("DELETE FROM lexical_indices")

    stale = backend.indexing.status(ref="HEAD")
    rebuild = backend.indexing.rebuild(all_refs=True)
    rebuilt_head = backend.indexing.status(ref="HEAD")
    indexed_results = backend.indexing.search(query="atlas", ref="HEAD", limit=5)
    graph_results = baseline.semantic_search("atlas", limit=5)

    assert stale["stale"] is True
    assert rebuild["rebuilt"] == 2
    assert set(rebuild["indexed_versions"]) == {first_commit.version_id, second_commit.version_id}
    assert rebuilt_head["stale"] is False
    assert [item["node"]["label"] for item in indexed_results] == [item["node"].label for item in graph_results]
