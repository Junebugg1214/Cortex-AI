from __future__ import annotations

from pathlib import Path

from cortex.agent.conflict_monitor import ConflictMonitor, ConflictMonitorConfig
from cortex.graph.graph import CortexGraph, Node
from cortex.graph.minds import _persist_mind_core_graph, init_mind, set_default_mind

REPO_ROOT = Path(__file__).resolve().parents[2]


def _node(label: str, *, source: str, timestamp: str) -> Node:
    return Node(
        id=f"pref:{label}".replace(" ", "_").lower(),
        label=label,
        tags=["communication_preferences"],
        confidence=0.9,
        provenance=[{"source": source, "method": "manual", "timestamp": timestamp}],
    )


def test_conflict_monitor_default_logs_stay_out_of_package_dir(tmp_path, monkeypatch) -> None:
    package_log_dir = REPO_ROOT / "cortex" / "agent" / "logs"
    store_dir = tmp_path / ".cortex"
    graph = CortexGraph()
    graph.add_node(_node("Prefers terse answers", source="chat-a", timestamp="2026-04-10T12:00:00Z"))
    graph.add_node(_node("Prefers detailed explanations", source="chat-b", timestamp="2026-04-11T12:00:00Z"))

    init_mind(store_dir, "self", owner="tester")
    set_default_mind(store_dir, "self")
    _persist_mind_core_graph(store_dir, "self", graph, message="seed conflicts", source="tests.agent.seed")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CORTEX_AGENT_LOG_DIR", raising=False)
    monkeypatch.delenv("CORTEX_STORE_DIR", raising=False)

    monitor = ConflictMonitor(ConflictMonitorConfig(store_dir=store_dir, mind_id="self", interactive=False))
    result = monitor.run_cycle()

    assert result["detected"] == 1
    assert list((store_dir / "logs").glob("*.log"))
    assert not package_log_dir.exists()
