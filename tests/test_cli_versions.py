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


def test_query_at_filters_temporal_graph(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Current Project"),
            label="Current Project",
            tags=["active_priorities"],
            confidence=0.9,
            status="active",
            valid_from="2026-01-01T00:00:00Z",
            valid_to="2026-12-31T00:00:00Z",
        )
    )
    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph)

    present_rc = main(["query", str(graph_path), "--node", "Current Project", "--at", "2026-06-01T00:00:00Z"])
    present_out = capsys.readouterr().out
    missing_rc = main(["query", str(graph_path), "--node", "Current Project", "--at", "2027-06-01T00:00:00Z"])
    missing_out = capsys.readouterr().out

    assert present_rc == 0
    assert "Current Project" in present_out
    assert missing_rc == 0
    assert "No node found" in missing_out


def test_blame_json_includes_provenance_and_version_history(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    store = VersionStore(store_dir)

    graph_v1 = CortexGraph()
    graph_v1.add_node(
        Node(
            id="n1",
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            confidence=0.8,
            provenance=[{"source": "import-a", "method": "extract"}],
        )
    )
    store.commit(graph_v1, "initial postgres", source="extraction")

    graph_v2 = CortexGraph()
    graph_v2.add_node(
        Node(
            id="n1",
            label="PostgreSQL",
            aliases=["postgres"],
            tags=["technical_expertise"],
            confidence=0.95,
            provenance=[{"source": "manual-a", "method": "manual"}],
            status="active",
        )
    )
    store.commit(graph_v2, "refine postgres", source="manual")

    graph_path = tmp_path / "context.json"
    _write_graph(graph_path, graph_v2)

    rc = main(
        [
            "blame",
            str(graph_path),
            "--label",
            "postgres",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["nodes"][0]["node"]["label"] == "PostgreSQL"
    assert out["nodes"][0]["provenance_sources"] == ["manual-a"]
    assert out["nodes"][0]["history"]["versions_seen"] == 2
    assert out["nodes"][0]["history"]["introduced_in"]["message"] == "initial postgres"


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


def test_memory_set_records_claim_event(tmp_path, capsys):
    graph_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    _write_graph(graph_path, CortexGraph())

    rc = main(
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
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["claim_id"]

    log_rc = main(
        [
            "claim",
            "log",
            "--store-dir",
            str(store_dir),
            "--label",
            "Project Atlas",
            "--format",
            "json",
        ]
    )
    log_out = json.loads(capsys.readouterr().out)
    assert log_rc == 0
    assert log_out["events"][0]["op"] == "assert"
    assert log_out["events"][0]["claim_id"] == out["claim_id"]

    show_rc = main(["claim", "show", out["claim_id"], "--store-dir", str(store_dir), "--format", "json"])
    show_out = json.loads(capsys.readouterr().out)
    assert show_rc == 0
    assert show_out["events"][0]["label"] == "Project Atlas"


def test_memory_retract_records_claim_event(tmp_path, capsys):
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id("Project Atlas"),
            label="Project Atlas",
            tags=["active_priorities"],
            provenance=[{"source": "manual-note", "method": "manual"}],
        )
    )
    graph_path = tmp_path / "context.json"
    store_dir = tmp_path / ".cortex"
    _write_graph(graph_path, graph)

    rc = main(
        [
            "memory",
            "retract",
            str(graph_path),
            "--source",
            "manual-note",
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["claim_event_ids"]

    log_rc = main(
        [
            "claim",
            "log",
            "--store-dir",
            str(store_dir),
            "--source",
            "manual-note",
            "--op",
            "retract",
            "--format",
            "json",
        ]
    )
    log_out = json.loads(capsys.readouterr().out)
    assert log_rc == 0
    assert log_out["events"][0]["op"] == "retract"
    assert log_out["events"][0]["label"] == "Project Atlas"


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
