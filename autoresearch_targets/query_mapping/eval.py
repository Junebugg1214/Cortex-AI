#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import load_manifest, normalize_text, safe_div
from cortex.graph import CortexGraph
from cortex.query import QueryEngine, parse_nl_query
from cortex.query_lang import execute_query, parse_query


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def labels_from_output(output, graph: CortexGraph) -> list[str]:
    if isinstance(output, list):
        return [item.get("label", "") for item in output if isinstance(item, dict)]
    if not isinstance(output, dict):
        return []
    if "path" in output:
        path = output["path"]
        if path and isinstance(path[0], str):
            return [graph.get_node(node_id).label for node_id in path if graph.get_node(node_id)]
        return [item.get("label", "") for item in path if isinstance(item, dict)]
    if "related" in output:
        return [item.get("label", "") for item in output["related"] if isinstance(item, dict)]
    if "neighbors" in output:
        return [item["node"].get("label", "") for item in output["neighbors"] if isinstance(item, dict)]
    if "results" in output:
        return [item.get("label", "") for item in output["results"] if isinstance(item, dict)]
    return []


def infer_kind(output) -> str:
    if isinstance(output, str):
        return "unrecognized"
    if isinstance(output, list):
        return "list"
    if not isinstance(output, dict):
        return "unknown"
    if "related" in output:
        return "related"
    if "path" in output:
        return "path"
    if "total_changed" in output:
        return "changed"
    if "neighbors" in output:
        return "neighbors"
    if "results" in output:
        return "search"
    return "dict"


def label_relevance(expected_labels: list[str], actual_labels: list[str]) -> float:
    if not expected_labels:
        return 1.0
    wanted = {normalize_text(label) for label in expected_labels}
    actual = {normalize_text(label) for label in actual_labels}
    return safe_div(len(wanted & actual), len(wanted))


def search_rank_score(expected_top: str, actual_labels: list[str]) -> float:
    wanted = normalize_text(expected_top)
    rank = None
    for index, label in enumerate(actual_labels, start=1):
        if normalize_text(label) == wanted:
            rank = index
            break
    if rank is None:
        return 0.0
    mrr = 1.0 / rank
    hit1 = 1.0 if rank == 1 else 0.0
    hit3 = 1.0 if rank <= 3 else 0.0
    return (0.40 * mrr) + (0.30 * hit1) + (0.30 * hit3)


def score_ast_case(case: dict) -> dict:
    try:
        ast = parse_query(case["query"])
        score = 1.0 if type(ast).__name__ == case["expected_type"] else 0.0
    except Exception:
        score = 0.0
    return {"id": case["id"], "score": score}


def score_nl_case(case: dict, graph: CortexGraph) -> dict:
    engine = QueryEngine(graph)
    output = parse_nl_query(case["query"], engine)
    kind_score = 1.0 if infer_kind(output) == case["expected_kind"] else 0.0
    relevance = label_relevance(case.get("expected_labels", []), labels_from_output(output, graph))
    score = (0.50 * kind_score) + (0.50 * relevance)
    return {"id": case["id"], "score": score, "kind": infer_kind(output), "relevance": relevance}


def score_dsl_case(case: dict, graph: CortexGraph) -> dict:
    output = execute_query(graph, case["query"])
    kind_score = 1.0 if output.get("type") == case["expected_kind"] else 0.0
    labels = labels_from_output(output, graph)
    if case["expected_kind"] == "search":
        relevance = search_rank_score(case["expected_top"], labels)
    else:
        relevance = label_relevance(case.get("expected_labels", []), labels)
    score = (0.40 * kind_score) + (0.60 * relevance)
    return {"id": case["id"], "score": score, "kind": output.get("type", "unknown"), "relevance": relevance}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate query-mapping autoresearch target")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--section", choices=["all", "ast", "nl", "dsl"], default="all")
    args = parser.parse_args()

    manifest = load_manifest(MANIFEST_PATH)
    graph = CortexGraph.from_v5_json(load_manifest(Path(manifest["graph_file"])))
    results: list[dict] = []

    if args.section in ("all", "ast"):
        results.extend(score_ast_case(case) for case in manifest["ast_cases"])
    if args.section in ("all", "nl"):
        results.extend(score_nl_case(case, graph) for case in manifest["nl_cases"])
    if args.section in ("all", "dsl"):
        results.extend(score_dsl_case(case, graph) for case in manifest["dsl_cases"])

    overall = safe_div(sum(result["score"] for result in results), len(results))

    if not args.quiet:
        print("Query-mapping evaluation")
        for result in results:
            print(f"- {result['id']}: score={result['score']:.4f}")

    print(f"query_mapping_score: {overall:.4f}")


if __name__ == "__main__":
    main()
