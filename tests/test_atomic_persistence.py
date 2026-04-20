from pathlib import Path

import cortex.governance as governance_mod
import cortex.portability.portable_runtime as portable_runtime_mod
import cortex.remotes as remotes_mod
import cortex.versioning.upai.versioning as versioning_mod
from cortex.atomic_io import atomic_write_text as real_atomic_write_text
from cortex.governance import GovernanceRule, GovernanceStore
from cortex.graph.graph import CortexGraph, Node
from cortex.portability.portable_runtime import PortabilityState, save_portability_state
from cortex.remotes import MemoryRemote, RemoteRegistry
from cortex.versioning.upai.versioning import VersionStore


def _record_atomic_writes(monkeypatch, module):
    calls: list[Path] = []

    def spy(path, text, *, encoding="utf-8"):
        target = Path(path)
        calls.append(target)
        return real_atomic_write_text(target, text, encoding=encoding)

    monkeypatch.setattr(module, "atomic_write_text", spy)
    return calls


def test_save_portability_state_uses_atomic_write(monkeypatch, tmp_path):
    store_dir = tmp_path / ".cortex"
    calls = _record_atomic_writes(monkeypatch, portable_runtime_mod)

    path = save_portability_state(store_dir, PortabilityState(updated_at="2026-04-10T12:00:00Z"))

    assert path in calls


def test_governance_store_uses_atomic_write(monkeypatch, tmp_path):
    store_dir = tmp_path / ".cortex"
    calls = _record_atomic_writes(monkeypatch, governance_mod)
    store = GovernanceStore(store_dir)

    store.upsert_rule(
        GovernanceRule(
            name="protect-main",
            effect="allow",
            actor_pattern="agent/*",
            actions=["write"],
            namespaces=["main"],
            require_approval=True,
        )
    )

    assert store.path in calls


def test_remote_registry_uses_atomic_write(monkeypatch, tmp_path):
    store_dir = tmp_path / ".cortex"
    calls = _record_atomic_writes(monkeypatch, remotes_mod)
    registry = RemoteRegistry(store_dir)

    registry.add(MemoryRemote(name="origin", path=str(tmp_path / "remote"), default_branch="main"))

    assert registry.path in calls


def test_version_store_commit_uses_atomic_writes(monkeypatch, tmp_path):
    store_dir = tmp_path / ".cortex"
    calls = _record_atomic_writes(monkeypatch, versioning_mod)
    store = VersionStore(store_dir)
    graph = CortexGraph()
    graph.add_node(Node(id="atlas", label="Project Atlas", tags=["active_priorities"], confidence=0.9))

    version = store.commit(graph, "baseline")

    assert store.history_path in calls
    assert store.head_path in calls
    assert store._branch_path("main") in calls
    assert (store.versions_dir / f"{version.version_id}.json") in calls
