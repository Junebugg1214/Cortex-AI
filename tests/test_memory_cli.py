import json

from cortex.cli import main
from cortex.graph import CortexGraph, Node, make_node_id


def _write_graph(path, graph: CortexGraph) -> None:
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_memory_show_json(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Python"), label="Python", tags=["technical_expertise"], confidence=0.9))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["memory", "show", str(graph_path), "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["nodes"][0]["label"] == "Python"


def test_memory_conflicts_json(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise", "negations"]))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["memory", "conflicts", str(graph_path), "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["conflicts"]


def test_memory_set_creates_node(tmp_path):
    graph = CortexGraph()
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(
        [
            "memory",
            "set",
            str(graph_path),
            "--label",
            "Response Style",
            "--tag",
            "communication_preferences",
            "--brief",
            "Prefers concise answers",
        ]
    )
    assert rc == 0
    saved = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    assert saved.find_nodes(label="Response Style")


def test_memory_forget_by_label(tmp_path):
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Python"), label="Python", tags=["technical_expertise"], confidence=0.9))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["memory", "forget", str(graph_path), "--label", "Python"])
    assert rc == 0
    saved = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    assert not saved.find_nodes(label="Python")


def test_memory_resolve_ignore(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise", "negations"]))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    conflicts_rc = main(["memory", "conflicts", str(graph_path), "--format", "json"])
    conflicts = json.loads(capsys.readouterr().out)["conflicts"]
    assert conflicts_rc == 0

    rc = main(
        [
            "memory",
            "resolve",
            str(graph_path),
            "--conflict-id",
            conflicts[0]["id"],
            "--action",
            "ignore",
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["status"] == "ok"


def test_contradictions_json(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise", "negations"]))
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["contradictions", str(graph_path), "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["contradictions"]
    assert out["contradictions"][0]["id"]


def test_contradictions_json_empty(tmp_path, capsys):
    graph = CortexGraph()
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["contradictions", str(graph_path), "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out == {"contradictions": []}
