import json

from cortex.governance import GovernanceRule, GovernanceStore
from cortex.graph import CortexGraph, Node
from cortex.remotes import RemoteRegistry
from cortex.schemas.memory_v1 import RemoteRecord
from cortex.storage import build_filesystem_backend
from cortex.upai.versioning import VersionStore
from cortex.webapp import MemoryUIBackend


def _write_graph(path, graph: CortexGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_filesystem_backend_versions_log_matches_version_store(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))

    store = VersionStore(store_dir)
    store.commit(graph, "baseline")
    store.commit(graph, "second")

    backend = build_filesystem_backend(store_dir)
    expected = [item.to_dict() for item in store.log(limit=10)]
    actual = [item.to_dict() for item in backend.versions.log(limit=10)]

    assert [item["version_id"] for item in actual] == [item["version_id"] for item in expected]
    assert actual[0]["message"] == expected[0]["message"]


def test_filesystem_backend_governance_matches_store(tmp_path):
    store_dir = tmp_path / ".cortex"
    governance = GovernanceStore(store_dir)
    governance.upsert_rule(
        GovernanceRule(
            name="protect-main",
            effect="allow",
            actor_pattern="agent/*",
            actions=["write"],
            namespaces=["main"],
            require_approval=True,
        )
    )

    backend = build_filesystem_backend(store_dir)
    rules = backend.governance.list_rules()
    decision = backend.governance.authorize("agent/coder", "write", "main")

    assert rules[0].name == "protect-main"
    assert decision.allowed is True
    assert decision.require_approval is True


def test_filesystem_backend_remotes_and_injected_webapp_backend(tmp_path):
    local_store_dir = tmp_path / "local" / ".cortex"
    remote_root = tmp_path / "remote"
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    context_path = tmp_path / "local" / "context.json"
    _write_graph(context_path, graph)

    VersionStore(local_store_dir).commit(graph, "baseline")

    backend = build_filesystem_backend(local_store_dir)
    backend.remotes.add_remote(RemoteRecord(name="origin", path=str(remote_root), default_branch="main"))

    registry = RemoteRegistry(local_store_dir)
    assert registry.get("origin") is not None

    ui_backend = MemoryUIBackend(store_dir=local_store_dir, context_file=context_path, backend=backend)
    meta = ui_backend.meta()
    remotes = ui_backend.list_remotes()

    assert meta["current_branch"] == "main"
    assert remotes["remotes"][0]["name"] == "origin"
    assert remotes["remotes"][0]["store_path"].endswith(".cortex")
    assert remotes["remotes"][0]["trusted_did"]
    assert remotes["remotes"][0]["allowed_namespaces"] == ["main"]
