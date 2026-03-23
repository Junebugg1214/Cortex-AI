#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import datetime, timezone
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


def node(label: str, tags: list[str], confidence: float = 0.9, brief: str = "", first_seen: str = "") -> Node:
    return Node(
        id=make_node_id(label),
        label=label,
        tags=tags,
        confidence=confidence,
        brief=brief,
        first_seen=first_seen,
    )


def export_graph(path: Path) -> None:
    graph = CortexGraph()
    nodes = [
        node("Marc", ["identity"], 0.99, "Builder working on Cortex"),
        node("Python", ["technical_expertise"], 0.95, "Programming language for automation"),
        node("Rust", ["technical_expertise"], 0.88, "Systems programming language"),
        node("Build CLI", ["active_priorities"], 0.93, "Current workstream for CLI improvements", "2026-01-10T00:00:00Z"),
        node("Healthcare", ["domain_knowledge"], 0.84, "Domain context for chart review"),
        node("GitHubCLI", ["technical_expertise"], 0.82, "Authenticate repositories from the terminal"),
        node("GitHub Actions", ["technical_expertise"], 0.81, "GitHub automation for CI pipelines"),
        node("OpenAPISpec", ["technical_expertise"], 0.8, "Contract for REST endpoints"),
        node("API Contract", ["technical_expertise"], 0.79, "Shared API contract template"),
    ]
    for item in nodes:
        graph.add_node(item)

    marc = make_node_id("Marc")
    python = make_node_id("Python")
    rust = make_node_id("Rust")
    build_cli = make_node_id("Build CLI")
    healthcare = make_node_id("Healthcare")

    edges = [
        Edge(id=make_edge_id(marc, python, "uses"), source_id=marc, target_id=python, relation="uses", confidence=0.9),
        Edge(
            id=make_edge_id(python, healthcare, "applied_in"),
            source_id=python,
            target_id=healthcare,
            relation="applied_in",
            confidence=0.8,
        ),
        Edge(
            id=make_edge_id(rust, build_cli, "used_in"),
            source_id=rust,
            target_id=build_cli,
            relation="used_in",
            confidence=0.75,
        ),
    ]
    for edge in edges:
        graph.add_edge(edge)

    write_json(path, graph.export_v5())


def main() -> None:
    ensure_dir(GRAPHS_DIR)
    graph_path = GRAPHS_DIR / "query_mapping_graph.json"
    export_graph(graph_path)

    manifest = {
        "target": "query_mapping",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph_file": str(graph_path),
        "ast_cases": [
            {"id": "ast_find", "query": 'FIND nodes WHERE tag = "technical_expertise" LIMIT 5', "expected_type": "FindQuery"},
            {"id": "ast_neighbors", "query": 'NEIGHBORS OF "Python"', "expected_type": "NeighborsQuery"},
            {"id": "ast_path", "query": 'PATH FROM "Marc" TO "Healthcare"', "expected_type": "PathQuery"},
            {"id": "ast_search", "query": 'SEARCH "github cli" LIMIT 3', "expected_type": "SearchQuery"},
        ],
        "nl_cases": [
            {
                "id": "nl_tech_stack",
                "query": "show my tech stack",
                "expected_kind": "list",
                "expected_labels": ["Python", "Rust"],
            },
            {
                "id": "nl_current_work",
                "query": "what am I working on right now",
                "expected_kind": "list",
                "expected_labels": ["Build CLI"],
            },
            {
                "id": "nl_connected_path",
                "query": "how is Marc connected to Healthcare",
                "expected_kind": "path",
                "expected_labels": ["Marc", "Python", "Healthcare"],
            },
            {
                "id": "nl_related",
                "query": "who is related to Python",
                "expected_kind": "related",
                "expected_labels": ["Marc", "Healthcare"],
            },
            {
                "id": "nl_changed",
                "query": "what changed since 2025-01-01",
                "expected_kind": "changed",
                "expected_labels": [],
            },
        ],
        "dsl_cases": [
            {
                "id": "dsl_search_github_cli",
                "query": 'SEARCH "github cli terminal"',
                "expected_kind": "search",
                "expected_top": "GitHubCLI",
            },
            {
                "id": "dsl_search_openapi",
                "query": 'SEARCH "open api contract"',
                "expected_kind": "search",
                "expected_top": "OpenAPISpec",
            },
            {
                "id": "dsl_path",
                "query": 'PATH FROM "Marc" TO "Healthcare"',
                "expected_kind": "path",
                "expected_labels": ["Marc", "Python", "Healthcare"],
            },
            {
                "id": "dsl_neighbors",
                "query": 'NEIGHBORS OF "Python"',
                "expected_kind": "neighbors",
                "expected_labels": ["Marc", "Healthcare"],
            },
        ],
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote query-mapping corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
