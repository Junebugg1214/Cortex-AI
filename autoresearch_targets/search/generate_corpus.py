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


def node(label: str, brief: str, tags: list[str] | None = None, props: dict | None = None) -> Node:
    return Node(
        id=make_node_id(label),
        label=label,
        tags=tags or [],
        confidence=0.9,
        brief=brief,
        properties=props or {},
    )


def export_graph(path: Path, nodes: list[Node]) -> None:
    graph = CortexGraph()
    for item in nodes:
        graph.add_node(item)
    write_json(path, graph.export_v5())


def main() -> None:
    ensure_dir(GRAPHS_DIR)
    cases: list[dict] = []

    graph_01 = GRAPHS_DIR / "test_01_github_cli.json"
    export_graph(
        graph_01,
        [
            node("GitHubCLI", "Authenticate repositories from the terminal", ["tool"], {"provider": "github"}),
            node("GitHub Actions", "GitHub automation for CI pipelines", ["tool"]),
            node("Terminal Auth", "Local terminal login workflow", ["tool"]),
        ],
    )
    cases.append(
        {
            "id": "test_01_github_cli_compound_label",
            "graph_file": str(graph_01),
            "query": "github cli terminal",
            "expected_top": "GitHubCLI",
        }
    )

    graph_02 = GRAPHS_DIR / "test_02_openapi.json"
    export_graph(
        graph_02,
        [
            node("OpenAPISpec", "Contract for REST endpoints", ["artifact"]),
            node("API Contract", "Shared API contract template", ["artifact"]),
            node("REST Guide", "Developer guide for endpoints", ["docs"]),
        ],
    )
    cases.append(
        {
            "id": "test_02_openapi_compound_label",
            "graph_file": str(graph_02),
            "query": "open api contract",
            "expected_top": "OpenAPISpec",
        }
    )

    graph_03 = GRAPHS_DIR / "test_03_timeseries.json"
    export_graph(
        graph_03,
        [
            node("TimeSeriesDB", "Chronological metrics warehouse", ["database"]),
            node("Metrics Database", "Metrics storage for dashboards", ["database"]),
            node("Logging Store", "Log storage and retention", ["database"]),
        ],
    )
    cases.append(
        {
            "id": "test_03_timeseries_compound_label",
            "graph_file": str(graph_03),
            "query": "time series db metrics",
            "expected_top": "TimeSeriesDB",
        }
    )

    graph_04 = GRAPHS_DIR / "test_04_plain_language.json"
    export_graph(
        graph_04,
        [
            node("Chart Review", "Clinician chart review workflow", ["workflow"]),
            node("Review Queue", "Queue management for approvals", ["workflow"]),
            node("Billing Review", "Review disputed invoices", ["workflow"]),
        ],
    )
    cases.append(
        {
            "id": "test_04_plain_language_control",
            "graph_file": str(graph_04),
            "query": "chart review clinician",
            "expected_top": "Chart Review",
        }
    )

    manifest = {
        "target": "search",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote search corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
