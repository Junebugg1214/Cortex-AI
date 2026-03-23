#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import ensure_dir, write_json
from cortex.graph import CortexGraph, Edge, Node, make_edge_id


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

    cases = []

    graph_01 = GRAPHS_DIR / "test_01_rule_used_in.json"
    export_graph(
        graph_01,
        [
            Node(id="n1", label="Python", tags=["technical_expertise"]),
            Node(id="n2", label="Build CLI", tags=["active_priorities"]),
        ],
    )
    cases.append(
        {
            "id": "test_01_rule_used_in",
            "graph_file": str(graph_01),
            "messages": [],
            "expected_edges": [{"source": "Python", "relation": "used_in", "target": "Build CLI"}],
        }
    )

    graph_02 = GRAPHS_DIR / "test_02_rule_works_at.json"
    export_graph(
        graph_02,
        [
            Node(id="n1", label="Marc", tags=["identity"]),
            Node(id="n2", label="Acme Health", tags=["business_context"]),
        ],
    )
    cases.append(
        {
            "id": "test_02_rule_works_at",
            "graph_file": str(graph_02),
            "messages": [],
            "expected_edges": [{"source": "Marc", "relation": "works_at", "target": "Acme Health"}],
        }
    )

    graph_03 = GRAPHS_DIR / "test_03_rule_motivated_by.json"
    export_graph(
        graph_03,
        [
            Node(id="n1", label="Auditability", tags=["values"]),
            Node(id="n2", label="Ship careful rollout", tags=["active_priorities"]),
        ],
    )
    cases.append(
        {
            "id": "test_03_rule_motivated_by",
            "graph_file": str(graph_03),
            "messages": [],
            "expected_edges": [{"source": "Auditability", "relation": "motivated_by", "target": "Ship careful rollout"}],
        }
    )

    graph_04 = GRAPHS_DIR / "test_04_proximity_only.json"
    export_graph(
        graph_04,
        [
            Node(id="n1", label="Python", tags=["technical_expertise"]),
            Node(id="n2", label="Healthcare", tags=["domain_knowledge"]),
            Node(id="n3", label="Yoga", tags=["mentions"]),
        ],
    )
    cases.append(
        {
            "id": "test_04_proximity_only",
            "graph_file": str(graph_04),
            "messages": ["Python helps with Healthcare reporting, and Yoga keeps me balanced."],
            "expected_edges": [
                {"source": "Healthcare", "relation": "co_mentioned", "target": "Python"},
                {"source": "Python", "relation": "applied_in", "target": "Healthcare"},
            ],
        }
    )

    graph_05 = GRAPHS_DIR / "test_05_proximity_far_apart.json"
    export_graph(
        graph_05,
        [
            Node(id="n1", label="Python", tags=["technical_expertise"]),
            Node(id="n2", label="Healthcare", tags=["mentions"]),
        ],
    )
    cases.append(
        {
            "id": "test_05_proximity_far_apart",
            "graph_file": str(graph_05),
            "messages": [f"Python {'x' * 240} Healthcare"],
            "expected_edges": [],
        }
    )

    graph_06 = GRAPHS_DIR / "test_06_rule_beats_proximity.json"
    export_graph(
        graph_06,
        [
            Node(id="n1", label="Python", tags=["technical_expertise"]),
            Node(id="n2", label="Refactor checkout", tags=["active_priorities"]),
        ],
    )
    cases.append(
        {
            "id": "test_06_rule_beats_proximity",
            "graph_file": str(graph_06),
            "messages": ["Python and Refactor checkout are mentioned in the same sentence."],
            "expected_edges": [{"source": "Python", "relation": "used_in", "target": "Refactor checkout"}],
        }
    )

    graph_07 = GRAPHS_DIR / "test_07_existing_edge_skipped.json"
    export_graph(
        graph_07,
        [
            Node(id="n1", label="Python", tags=["technical_expertise"]),
            Node(id="n2", label="Build CLI", tags=["active_priorities"]),
        ],
        [
            Edge(
                id=make_edge_id("n1", "n2", "used_in"),
                source_id="n1",
                target_id="n2",
                relation="used_in",
                confidence=0.9,
            )
        ],
    )
    cases.append(
        {
            "id": "test_07_existing_edge_skipped",
            "graph_file": str(graph_07),
            "messages": ["Python and Build CLI are still nearby in the latest note."],
            "expected_edges": [],
        }
    )

    graph_08 = GRAPHS_DIR / "test_08_relationships_associated_with.json"
    export_graph(
        graph_08,
        [
            Node(id="n1", label="OpenAI team", tags=["relationships"]),
            Node(id="n2", label="Cortex AI", tags=["business_context"]),
        ],
    )
    cases.append(
        {
            "id": "test_08_relationships_associated_with",
            "graph_file": str(graph_08),
            "messages": [],
            "expected_edges": [{"source": "OpenAI team", "relation": "associated_with", "target": "Cortex AI"}],
        }
    )

    manifest = {
        "target": "edge_extraction",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote edge extraction corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
