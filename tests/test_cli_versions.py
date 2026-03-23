import json

from cortex.cli import main
from cortex.graph import CortexGraph, Node, make_node_id
from cortex.upai.versioning import VersionStore


def _write_graph(path, graph: CortexGraph) -> None:
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_query_search_uses_alias(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("PostgreSQL"),
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            confidence=0.9,
        )
    )
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    rc = main(["query", str(graph_path), "--search", "postgres"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "PostgreSQL" in out
    assert "aliases: postgres" in out


def test_memory_set_supports_alias_temporal_and_provenance(tmp_path):
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, CortexGraph())

    rc = main(
        [
            "memory",
            "set",
            str(graph_path),
            "--label",
            "PostgreSQL",
            "--tag",
            "technical_expertise",
            "--alias",
            "postgres",
            "--valid-from",
            "2026-01-01T00:00:00Z",
            "--status",
            "active",
            "--source",
            "manual-test",
        ]
    )

    assert rc == 0
    saved = CortexGraph.from_v5_json(json.loads(graph_path.read_text(encoding="utf-8")))
    node = saved.find_nodes(label="postgres")[0]
    assert node.label == "PostgreSQL"
    assert node.valid_from == "2026-01-01T00:00:00Z"
    assert node.status == "active"
    assert node.provenance[0]["source"] == "manual-test"


def test_version_diff_and_checkout_cli(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)

    graph_a = CortexGraph()
    graph_a.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.8))
    version_a = store.commit(graph_a, "first")

    graph_b = CortexGraph()
    graph_b.add_node(Node(id="n1", label="Python", tags=["technical_expertise"], confidence=0.9))
    graph_b.add_node(Node(id="n2", label="Rust", tags=["technical_expertise"], confidence=0.7))
    version_b = store.commit(graph_b, "second")

    diff_rc = main(["diff", version_a.version_id[:8], version_b.version_id[:8], "--store-dir", str(store_dir), "--format", "json"])
    diff_out = json.loads(capsys.readouterr().out)
    assert diff_rc == 0
    assert "n2" in diff_out["added"]
    assert diff_out["modified"][0]["node_id"] == "n1"

    output_path = tmp_path / "checked_out.json"
    checkout_rc = main(
        [
            "checkout",
            version_b.version_id[:8],
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_path),
        ]
    )
    assert checkout_rc == 0
    checked_out = CortexGraph.from_v5_json(json.loads(output_path.read_text(encoding="utf-8")))
    assert "n2" in checked_out.nodes
