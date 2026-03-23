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


def export_graph(path: Path, nodes: list[Node], edges: list[Edge]) -> None:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    for edge in edges:
        graph.add_edge(edge)
    write_json(path, graph.export_v5())


def edge(edge_id: str, source_id: str, target_id: str, relation: str = "related_to") -> Edge:
    return Edge(id=edge_id, source_id=source_id, target_id=target_id, relation=relation, confidence=0.8)


def main() -> None:
    ensure_dir(GRAPHS_DIR)
    cases: list[dict] = []

    graph_01 = GRAPHS_DIR / "test_01_k8s.json"
    export_graph(
        graph_01,
        [
            Node(id="k8s", label="K8s", tags=["technical_expertise"]),
            Node(id="kube", label="Kubernetes", tags=["technical_expertise"]),
            Node(id="helm", label="Helm", tags=["technical_expertise"]),
        ],
        [
            edge("e1", "k8s", "helm"),
            edge("e2", "kube", "helm"),
        ],
    )
    cases.append(
        {
            "id": "test_01_k8s_alias",
            "graph_file": str(graph_01),
            "threshold": 0.8,
            "expected_pairs": [["K8s", "Kubernetes"]],
            "expected_remaining": ["K8s", "Helm"],
        }
    )

    graph_02 = GRAPHS_DIR / "test_02_js.json"
    export_graph(
        graph_02,
        [
            Node(id="js", label="JS", tags=["technical_expertise"]),
            Node(id="javascript", label="JavaScript", tags=["technical_expertise"]),
            Node(id="react", label="React", tags=["technical_expertise"]),
        ],
        [
            edge("e1", "js", "react"),
            edge("e2", "javascript", "react"),
        ],
    )
    cases.append(
        {
            "id": "test_02_js_alias",
            "graph_file": str(graph_02),
            "threshold": 0.8,
            "expected_pairs": [["JS", "JavaScript"]],
            "expected_remaining": ["JS", "React"],
        }
    )

    graph_03 = GRAPHS_DIR / "test_03_postgres.json"
    export_graph(
        graph_03,
        [
            Node(id="postgres", label="Postgres", tags=["technical_expertise"]),
            Node(id="postgresql", label="PostgreSQL", tags=["technical_expertise"]),
            Node(id="sqlalchemy", label="SQLAlchemy", tags=["technical_expertise"]),
        ],
        [
            edge("e1", "postgres", "sqlalchemy"),
            edge("e2", "postgresql", "sqlalchemy"),
        ],
    )
    cases.append(
        {
            "id": "test_03_postgres_alias",
            "graph_file": str(graph_03),
            "threshold": 0.8,
            "expected_pairs": [["Postgres", "PostgreSQL"]],
            "expected_remaining": ["Postgres", "SQLAlchemy"],
        }
    )

    graph_04 = GRAPHS_DIR / "test_04_false_positive.json"
    export_graph(
        graph_04,
        [
            Node(id="privacy", label="Data Privacy", tags=["values"]),
            Node(id="pipeline", label="Data Pipeline", tags=["values"]),
            Node(id="governance", label="Governance", tags=["values"]),
        ],
        [],
    )
    cases.append(
        {
            "id": "test_04_false_positive_protection",
            "graph_file": str(graph_04),
            "threshold": 0.8,
            "expected_pairs": [],
            "expected_remaining": ["Data Privacy", "Data Pipeline", "Governance"],
        }
    )

    graph_05 = GRAPHS_DIR / "test_05_typescript_version.json"
    export_graph(
        graph_05,
        [
            Node(id="ts54", label="TypeScript 5.4", tags=["technical_expertise"]),
            Node(id="ts", label="TypeScript", tags=["technical_expertise"]),
            Node(id="tsx", label="React", tags=["technical_expertise"]),
        ],
        [
            edge("e1", "ts54", "tsx"),
            edge("e2", "ts", "tsx"),
        ],
    )
    cases.append(
        {
            "id": "test_05_version_suffix",
            "graph_file": str(graph_05),
            "threshold": 0.8,
            "expected_pairs": [["TypeScript", "TypeScript 5.4"]],
            "expected_remaining": ["TypeScript 5.4", "React"],
        }
    )

    manifest = {
        "target": "dedup",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote dedup corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
