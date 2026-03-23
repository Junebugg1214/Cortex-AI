#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import ensure_dir, write_json
from cortex.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id


HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE / "corpus"
GRAPHS_DIR = CORPUS_DIR / "graphs"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"


def export_graph(path: Path, nodes: list[Node], edges: list[Edge] | None = None) -> None:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    for edge in edges or []:
        graph.add_edge(edge)
    write_json(path, graph.export_v5())


def main() -> None:
    ensure_dir(GRAPHS_DIR)
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_ts = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

    cases: list[dict] = []

    graph_01 = GRAPHS_DIR / "test_01_stale_snapshot_only.json"
    export_graph(
        graph_01,
        [
            Node(
                id=make_node_id("Dormant API"),
                label="Dormant API",
                tags=["history"],
                snapshots=[{"timestamp": old_ts, "source": "import"}],
            ),
            Node(
                id=make_node_id("Fresh API"),
                label="Fresh API",
                tags=["history"],
                snapshots=[{"timestamp": recent_ts, "source": "import"}],
            ),
        ],
    )
    cases.append(
        {
            "id": "test_01_stale_snapshot_only",
            "kind": "stale",
            "graph_file": str(graph_01),
            "expected_labels": ["Dormant API"],
        }
    )

    graph_02 = GRAPHS_DIR / "test_02_confidence_gap.json"
    export_graph(
        graph_02,
        [
            Node(id=make_node_id("Launch Beta"), label="Launch Beta", tags=["active_priorities"], confidence=0.4),
            Node(id=make_node_id("Stable Release"), label="Stable Release", tags=["active_priorities"], confidence=0.9),
        ],
    )
    cases.append(
        {
            "id": "test_02_confidence_gap",
            "kind": "confidence",
            "graph_file": str(graph_02),
            "expected_labels": ["Launch Beta"],
        }
    )

    graph_03 = GRAPHS_DIR / "test_03_relationship_gap.json"
    export_graph(
        graph_03,
        [
            Node(id="biz1", label="Acme", tags=["business_context"]),
            Node(id="biz2", label="BetaCo", tags=["business_context"]),
            Node(id="biz3", label="Gamma Labs", tags=["business_context"]),
        ],
    )
    cases.append(
        {
            "id": "test_03_relationship_gap",
            "kind": "relationship",
            "graph_file": str(graph_03),
            "expected_tags": ["business_context"],
        }
    )

    prev_04 = GRAPHS_DIR / "test_04_prev_repeated_contradiction.json"
    cur_04 = GRAPHS_DIR / "test_04_cur_repeated_contradiction.json"
    repeated_node = Node(
        id=make_node_id("Python"),
        label="Python",
        tags=["technical_expertise", "negations"],
        confidence=0.8,
    )
    export_graph(prev_04, [repeated_node])
    export_graph(cur_04, [repeated_node])
    cases.append(
        {
            "id": "test_04_repeated_contradiction_not_new",
            "kind": "digest_contradictions",
            "previous_graph_file": str(prev_04),
            "current_graph_file": str(cur_04),
            "expected_types": [],
        }
    )

    prev_05 = GRAPHS_DIR / "test_05_prev_clean.json"
    cur_05 = GRAPHS_DIR / "test_05_cur_new_contradiction.json"
    export_graph(
        prev_05,
        [Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise"], confidence=0.8)],
    )
    export_graph(
        cur_05,
        [Node(id=make_node_id("Rust"), label="Rust", tags=["technical_expertise", "negations"], confidence=0.8)],
    )
    cases.append(
        {
            "id": "test_05_new_contradiction_added",
            "kind": "digest_contradictions",
            "previous_graph_file": str(prev_05),
            "current_graph_file": str(cur_05),
            "expected_types": ["negation_conflict"],
        }
    )

    prev_06 = GRAPHS_DIR / "test_06_prev_structure.json"
    cur_06 = GRAPHS_DIR / "test_06_cur_structure.json"
    python_id = make_node_id("Python")
    legacy_id = make_node_id("Legacy CLI")
    audit_id = make_node_id("Audit Trail")
    export_graph(
        prev_06,
        [
            Node(id=python_id, label="Python", tags=["technical_expertise"], confidence=0.9),
            Node(id=legacy_id, label="Legacy CLI", tags=["technical_expertise"], confidence=0.6),
        ],
    )
    export_graph(
        cur_06,
        [
            Node(id=python_id, label="Python", tags=["technical_expertise"], confidence=0.9),
            Node(id=audit_id, label="Audit Trail", tags=["active_priorities"], confidence=0.85),
        ],
        [
            Edge(
                id=make_edge_id(python_id, audit_id, "used_in"),
                source_id=python_id,
                target_id=audit_id,
                relation="used_in",
                confidence=0.8,
            )
        ],
    )
    cases.append(
        {
            "id": "test_06_digest_structure",
            "kind": "digest_structure",
            "previous_graph_file": str(prev_06),
            "current_graph_file": str(cur_06),
            "expected_new_nodes": ["Audit Trail"],
            "expected_removed_nodes": ["Legacy CLI"],
            "expected_new_edges": [["Python", "used_in", "Audit Trail"]],
        }
    )

    manifest = {
        "target": "intelligence",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote intelligence corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
