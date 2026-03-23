#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import ensure_dir, write_json
from cortex.graph import CortexGraph, Node, make_node_id


HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE / "corpus"
GRAPHS_DIR = CORPUS_DIR / "graphs"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"


def export_graph(path: Path, nodes: list[Node]) -> None:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    write_json(path, graph.export_v5())


def main() -> None:
    ensure_dir(GRAPHS_DIR)
    cases = []

    graph_01 = GRAPHS_DIR / "test_01_negation.json"
    export_graph(
        graph_01,
        [
            Node(
                id=make_node_id("Python"),
                label="Python",
                tags=["technical_expertise", "negations"],
                confidence=0.8,
            )
        ],
    )
    cases.append(
        {
            "id": "test_01_negation_conflict",
            "graph_file": str(graph_01),
            "expected": [{"type": "negation_conflict", "label": "Python", "resolution": "needs_review"}],
        }
    )

    graph_02 = GRAPHS_DIR / "test_02_temporal_flip.json"
    export_graph(
        graph_02,
        [
            Node(
                id=make_node_id("Rust"),
                label="Rust",
                tags=["technical_expertise"],
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.3, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.8, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-03-01T00:00:00Z", "confidence": 0.4, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-04-01T00:00:00Z", "confidence": 0.9, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                ],
            )
        ],
    )
    cases.append(
        {
            "id": "test_02_temporal_flip",
            "graph_file": str(graph_02),
            "expected": [{"type": "temporal_flip", "label": "Rust", "resolution": "prefer_newer"}],
        }
    )

    graph_03 = GRAPHS_DIR / "test_03_source_conflict.json"
    export_graph(
        graph_03,
        [
            Node(
                id=make_node_id("Acme roadmap"),
                label="Acme roadmap",
                tags=["active_priorities"],
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.8, "tags": ["active_priorities"], "source": "file_a", "description_hash": "hash_1"}
                ],
            ),
            Node(
                id=make_node_id("Acme roadmap") + "x",
                label="Acme roadmap",
                tags=["active_priorities"],
                snapshots=[
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.7, "tags": ["active_priorities"], "source": "file_b", "description_hash": "hash_2"}
                ],
            ),
        ],
    )
    cases.append(
        {
            "id": "test_03_source_conflict",
            "graph_file": str(graph_03),
            "expected": [{"type": "source_conflict", "label": "Acme roadmap", "resolution": "prefer_higher_confidence"}],
        }
    )

    graph_04 = GRAPHS_DIR / "test_04_tag_conflict.json"
    export_graph(
        graph_04,
        [
            Node(
                id=make_node_id("JavaScript"),
                label="JavaScript",
                tags=["technical_expertise"],
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.6, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.4, "tags": ["negations"], "source": "a", "description_hash": "h1"},
                ],
            )
        ],
    )
    cases.append(
        {
            "id": "test_04_tag_conflict",
            "graph_file": str(graph_04),
            "expected": [{"type": "tag_conflict", "label": "JavaScript", "resolution": "prefer_newer"}],
        }
    )

    graph_05 = GRAPHS_DIR / "test_05_clean.json"
    export_graph(
        graph_05,
        [
            Node(
                id=make_node_id("Healthcare"),
                label="Healthcare",
                tags=["domain_knowledge"],
                confidence=0.7,
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.50, "tags": ["domain_knowledge"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.52, "tags": ["domain_knowledge"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-03-01T00:00:00Z", "confidence": 0.50, "tags": ["domain_knowledge"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-04-01T00:00:00Z", "confidence": 0.52, "tags": ["domain_knowledge"], "source": "a", "description_hash": "h1"},
                ],
            )
        ],
    )
    cases.append(
        {
            "id": "test_05_clean_graph",
            "graph_file": str(graph_05),
            "expected": [],
        }
    )

    graph_06 = GRAPHS_DIR / "test_06_multi_conflict.json"
    export_graph(
        graph_06,
        [
            Node(
                id=make_node_id("TypeScript"),
                label="TypeScript",
                tags=["technical_expertise", "negations"],
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.3, "tags": ["negations"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.7, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                ],
            ),
            Node(
                id=make_node_id("Payments API"),
                label="Payments API",
                tags=["active_priorities"],
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.9, "tags": ["active_priorities"], "source": "roadmap", "description_hash": "hash_a"}
                ],
            ),
            Node(
                id=make_node_id("Payments API") + "x",
                label="Payments API",
                tags=["active_priorities"],
                snapshots=[
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.6, "tags": ["active_priorities"], "source": "notes", "description_hash": "hash_b"}
                ],
            ),
        ],
    )
    cases.append(
        {
            "id": "test_06_multi_conflict",
            "graph_file": str(graph_06),
            "expected": [
                {"type": "negation_conflict", "label": "TypeScript", "resolution": "needs_review"},
                {"type": "tag_conflict", "label": "TypeScript", "resolution": "prefer_newer"},
                {"type": "source_conflict", "label": "Payments API", "resolution": "prefer_higher_confidence"},
            ],
        }
    )

    graph_07 = GRAPHS_DIR / "test_07_same_hash_no_conflict.json"
    export_graph(
        graph_07,
        [
            Node(
                id=make_node_id("Python SDK"),
                label="Python SDK",
                tags=["technical_expertise"],
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.7, "tags": ["technical_expertise"], "source": "file_a", "description_hash": "same"}
                ],
            ),
            Node(
                id=make_node_id("Python SDK") + "x",
                label="Python SDK",
                tags=["technical_expertise"],
                snapshots=[
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.8, "tags": ["technical_expertise"], "source": "file_b", "description_hash": "same"}
                ],
            ),
        ],
    )
    cases.append(
        {
            "id": "test_07_same_hash_no_conflict",
            "graph_file": str(graph_07),
            "expected": [],
        }
    )

    graph_08 = GRAPHS_DIR / "test_08_repeated_tag_flip.json"
    export_graph(
        graph_08,
        [
            Node(
                id=make_node_id("Node.js"),
                label="Node.js",
                tags=["technical_expertise"],
                snapshots=[
                    {"timestamp": "2025-01-01T00:00:00Z", "confidence": 0.7, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-02-01T00:00:00Z", "confidence": 0.5, "tags": ["negations"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-03-01T00:00:00Z", "confidence": 0.8, "tags": ["technical_expertise"], "source": "a", "description_hash": "h1"},
                    {"timestamp": "2025-04-01T00:00:00Z", "confidence": 0.4, "tags": ["negations"], "source": "a", "description_hash": "h1"},
                ],
            )
        ],
    )
    cases.append(
        {
            "id": "test_08_repeated_tag_flip",
            "graph_file": str(graph_08),
            "expected": [{"type": "tag_conflict", "label": "Node.js", "resolution": "prefer_newer"}],
        }
    )

    manifest = {
        "target": "contradictions",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote contradictions corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
