from __future__ import annotations

import json
from pathlib import Path

from cortex.cli import _route_cli_v2_argv, build_parser, main
from cortex.graph import CortexGraph, Edge, Node
from cortex.storage import build_sqlite_backend


def test_integrity_help_lists_check_subcommand(capsys):
    parser = build_parser(show_all_commands=True)
    argv, _ = _route_cli_v2_argv(["admin", "integrity", "--help"])

    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        assert exc.code == 0

    help_text = capsys.readouterr().out
    assert "check" in help_text
    assert "version chains" in help_text


def test_integrity_check_returns_json_payload_for_clean_store(tmp_path: Path, capsys):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"], provenance=[{"source": "doc"}]))
    backend.versions.commit(graph, "seed")

    rc = main(["admin", "integrity", "check", "--store-dir", str(store_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["graph_integrity"]["status"] == "ok"
    assert payload["head"]


def test_integrity_check_prints_warning_for_orphaned_nodes(tmp_path: Path, capsys):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"]))
    backend.versions.commit(graph, "seed")

    rc = main(["admin", "integrity", "check", "--store-dir", str(store_dir)])
    output = capsys.readouterr().out

    assert rc == 0
    assert "Integrity check: WARNING" in output
    assert "orphaned_nodes" in output


def test_integrity_check_exits_nonzero_for_error_state(tmp_path: Path, capsys):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"], provenance=[{"source": "doc"}]))
    graph.add_edge(Edge(id="e1", source_id="n1", target_id="missing", relation="depends_on"))
    backend.versions.commit(graph, "seed")

    rc = main(["admin", "integrity", "check", "--store-dir", str(store_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["status"] == "error"
    assert payload["graph_integrity"]["broken_edges"][0]["id"] == "e1"
