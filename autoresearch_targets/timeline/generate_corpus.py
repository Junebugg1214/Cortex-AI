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
    cases: list[dict] = []

    graph_01 = GRAPHS_DIR / "test_01_date_only.json"
    export_graph(
        graph_01,
        [
            Node(
                id=make_node_id("Python"),
                label="Python",
                tags=["technical_expertise"],
                first_seen="2025-01-15",
            )
        ],
    )
    cases.append(
        {
            "id": "test_01_date_only_normalization",
            "graph_file": str(graph_01),
            "expected_events": [
                {"label": "Python", "event_type": "first_seen", "timestamp": "2025-01-15T00:00:00Z"}
            ],
        }
    )

    graph_02 = GRAPHS_DIR / "test_02_timezone_ordering.json"
    export_graph(
        graph_02,
        [
            Node(
                id=make_node_id("Late Commit"),
                label="Late Commit",
                tags=["history"],
                first_seen="2025-01-10T23:30:00-05:00",
            ),
            Node(
                id=make_node_id("Early Review"),
                label="Early Review",
                tags=["history"],
                first_seen="2025-01-11T01:00:00Z",
            ),
        ],
    )
    cases.append(
        {
            "id": "test_02_timezone_ordering",
            "graph_file": str(graph_02),
            "expected_events": [
                {"label": "Early Review", "event_type": "first_seen", "timestamp": "2025-01-11T01:00:00Z"},
                {"label": "Late Commit", "event_type": "first_seen", "timestamp": "2025-01-11T04:30:00Z"},
            ],
        }
    )

    graph_03 = GRAPHS_DIR / "test_03_snapshot_offset.json"
    export_graph(
        graph_03,
        [
            Node(
                id=make_node_id("Deployment"),
                label="Deployment",
                tags=["history"],
                snapshots=[
                    {
                        "timestamp": "2025-02-01T15:00:00+02:00",
                        "source": "scheduler",
                        "confidence": 0.9,
                        "tags": ["history"],
                    }
                ],
            )
        ],
    )
    cases.append(
        {
            "id": "test_03_snapshot_normalization",
            "graph_file": str(graph_03),
            "expected_events": [
                {"label": "Deployment", "event_type": "snapshot", "timestamp": "2025-02-01T13:00:00Z"}
            ],
        }
    )

    graph_04 = GRAPHS_DIR / "test_04_range_filter.json"
    export_graph(
        graph_04,
        [
            Node(
                id=make_node_id("Bridge Event"),
                label="Bridge Event",
                tags=["history"],
                first_seen="2025-01-31T23:00:00-02:00",
            ),
            Node(
                id=make_node_id("March Event"),
                label="March Event",
                tags=["history"],
                first_seen="2025-03-10",
            ),
            Node(
                id=make_node_id("April Event"),
                label="April Event",
                tags=["history"],
                first_seen="2025-04-01T00:00:00Z",
            ),
        ],
    )
    cases.append(
        {
            "id": "test_04_normalized_range_filter",
            "graph_file": str(graph_04),
            "from_date": "2025-02-01T00:00:00Z",
            "to_date": "2025-03-31T23:59:59Z",
            "expected_events": [
                {"label": "Bridge Event", "event_type": "first_seen", "timestamp": "2025-02-01T01:00:00Z"},
                {"label": "March Event", "event_type": "first_seen", "timestamp": "2025-03-10T00:00:00Z"},
            ],
        }
    )

    manifest = {
        "target": "timeline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote timeline corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
