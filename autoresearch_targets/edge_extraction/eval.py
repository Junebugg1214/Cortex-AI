#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import f1_score, load_manifest, normalize_text, safe_div
from cortex.edge_extraction import discover_all_edges
from cortex.graph import CortexGraph


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def canonical_expected(edge: dict) -> tuple[str, str, str]:
    source = normalize_text(edge["source"])
    relation = edge["relation"]
    target = normalize_text(edge["target"])
    if relation == "co_mentioned":
        a, b = sorted([source, target])
        return (a, relation, b)
    return (source, relation, target)


def canonical_predicted(edge, graph: CortexGraph) -> tuple[str, str, str]:
    source = normalize_text(graph.get_node(edge.source_id).label)
    relation = edge.relation
    target = normalize_text(graph.get_node(edge.target_id).label)
    if relation == "co_mentioned":
        a, b = sorted([source, target])
        return (a, relation, b)
    return (source, relation, target)


def score_case(case: dict) -> dict:
    graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
    predicted = {
        canonical_predicted(edge, graph)
        for edge in discover_all_edges(graph, messages=case.get("messages", []))
    }
    expected = {canonical_expected(edge) for edge in case.get("expected_edges", [])}
    score = f1_score(expected, predicted)
    return {"id": case["id"], "score": score, "expected": len(expected), "predicted": len(predicted)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate edge extraction autoresearch target")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--case", default="")
    args = parser.parse_args()

    manifest = load_manifest(MANIFEST_PATH)
    cases = manifest["cases"]
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]

    results = [score_case(case) for case in cases]
    overall = safe_div(sum(result["score"] for result in results), len(results))

    if not args.quiet:
        print("Edge extraction evaluation")
        for result in results:
            print(
                f"- {result['id']}: score={result['score']:.4f} "
                f"(expected={result['expected']}, predicted={result['predicted']})"
            )

    print(f"edge_extraction_score: {overall:.4f}")


if __name__ == "__main__":
    main()
