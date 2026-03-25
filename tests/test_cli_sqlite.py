import json

from cortex.cli import main
from cortex.graph import CortexGraph, Node
from cortex.storage.sqlite import sqlite_db_path


def _write_graph(path, graph: CortexGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_cli_version_control_flows_use_sqlite_backend(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_STORAGE_BACKEND", "sqlite")
    store_dir = tmp_path / ".cortex"
    graph_path = tmp_path / "context.json"

    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    _write_graph(graph_path, base_graph)

    commit_main_rc = main(["commit", str(graph_path), "-m", "main base", "--store-dir", str(store_dir)])
    commit_main_out = capsys.readouterr().out
    assert commit_main_rc == 0
    assert "Branch: main" in commit_main_out
    assert sqlite_db_path(store_dir).exists()

    branch_rc = main(["branch", "feature/atlas", "--store-dir", str(store_dir), "--format", "json"])
    branch_out = json.loads(capsys.readouterr().out)
    assert branch_rc == 0
    assert branch_out["branch"] == "feature/atlas"

    switch_rc = main(["switch", "feature/atlas", "--store-dir", str(store_dir)])
    switch_out = capsys.readouterr().out
    assert switch_rc == 0
    assert "Switched to feature/atlas" in switch_out

    feature_graph = CortexGraph()
    feature_graph.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    feature_graph.add_node(Node(id="n2", label="Project Atlas", tags=["active_priorities"], confidence=0.9))
    _write_graph(graph_path, feature_graph)

    commit_feature_rc = main(["commit", str(graph_path), "-m", "feature add atlas", "--store-dir", str(store_dir)])
    capsys.readouterr()
    assert commit_feature_rc == 0

    log_rc = main(["log", "--store-dir", str(store_dir), "--branch", "feature/atlas"])
    log_out = capsys.readouterr().out
    assert log_rc == 0
    assert "feature add atlas" in log_out
    assert "(feature/atlas)" in log_out

    diff_rc = main(["diff", "main", "feature/atlas", "--store-dir", str(store_dir), "--format", "json"])
    diff_out = json.loads(capsys.readouterr().out)
    assert diff_rc == 0
    assert "n2" in diff_out["added"]

    output_path = tmp_path / "feature_checked_out.json"
    checkout_rc = main(["checkout", "feature/atlas", "--store-dir", str(store_dir), "--output", str(output_path)])
    capsys.readouterr()
    assert checkout_rc == 0
    checked_out = CortexGraph.from_v5_json(json.loads(output_path.read_text(encoding="utf-8")))
    assert "n2" in checked_out.nodes


def test_cli_claim_history_and_remote_flows_use_sqlite_backend(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_STORAGE_BACKEND", "sqlite")
    store_dir = tmp_path / ".cortex"
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, CortexGraph())

    set_rc = main(
        [
            "memory",
            "set",
            str(graph_path),
            "--label",
            "Project Atlas",
            "--tag",
            "active_priorities",
            "--status",
            "active",
            "--source",
            "manual-note",
            "--store-dir",
            str(store_dir),
            "--commit-message",
            "seed atlas",
            "--format",
            "json",
        ]
    )
    set_out = json.loads(capsys.readouterr().out)
    assert set_rc == 0
    assert set_out["claim_id"]
    assert set_out["commit_id"]

    log_rc = main(["claim", "log", "--store-dir", str(store_dir), "--label", "Project Atlas", "--format", "json"])
    log_out = json.loads(capsys.readouterr().out)
    assert log_rc == 0
    assert log_out["events"][0]["op"] == "assert"

    show_rc = main(["claim", "show", set_out["claim_id"], "--store-dir", str(store_dir), "--format", "json"])
    show_out = json.loads(capsys.readouterr().out)
    assert show_rc == 0
    assert show_out["events"][0]["label"] == "Project Atlas"

    blame_rc = main(
        ["blame", str(graph_path), "--label", "Project Atlas", "--store-dir", str(store_dir), "--format", "json"]
    )
    blame_out = json.loads(capsys.readouterr().out)
    assert blame_rc == 0
    assert blame_out["nodes"][0]["history"]["versions_seen"] == 1
    assert blame_out["nodes"][0]["claim_lineage"]["event_count"] == 1

    history_rc = main(
        ["history", str(graph_path), "--label", "Project Atlas", "--store-dir", str(store_dir), "--format", "json"]
    )
    history_out = json.loads(capsys.readouterr().out)
    assert history_rc == 0
    assert history_out["nodes"][0]["history"]["introduced_in"]["message"] == "seed atlas"

    remote_root = tmp_path / "remote"
    add_rc = main(["remote", "add", "origin", str(remote_root), "--store-dir", str(store_dir), "--format", "json"])
    add_out = json.loads(capsys.readouterr().out)
    assert add_rc == 0
    assert add_out["remote"]["name"] == "origin"

    push_rc = main(["remote", "push", "origin", "--branch", "main", "--store-dir", str(store_dir), "--format", "json"])
    push_out = json.loads(capsys.readouterr().out)
    assert push_rc == 0
    assert push_out["head"] == set_out["commit_id"]

    clone_store_dir = tmp_path / "clone" / ".cortex"
    assert main(["remote", "add", "origin", str(remote_root), "--store-dir", str(clone_store_dir)]) == 0
    capsys.readouterr()
    pull_rc = main(
        [
            "remote",
            "pull",
            "origin",
            "--branch",
            "main",
            "--into-branch",
            "imported/main",
            "--store-dir",
            str(clone_store_dir),
            "--format",
            "json",
        ]
    )
    pull_out = json.loads(capsys.readouterr().out)
    assert pull_rc == 0
    assert pull_out["branch"] == "imported/main"
