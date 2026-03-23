#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import f1_score, load_manifest, normalize_text, safe_div
from cortex.dedup import deduplicate, find_duplicates
from cortex.graph import CortexGraph


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def canonical_pair(label_a: str, label_b: str) -> tuple[str, str]:
    return tuple(sorted([normalize_text(label_a), normalize_text(label_b)]))


def predicted_pairs(graph: CortexGraph, threshold: float) -> set[tuple[str, str]]:
    pairs = set()
    for node_id_a, node_id_b, _score in find_duplicates(graph, threshold=threshold):
        node_a = graph.get_node(node_id_a)
        node_b = graph.get_node(node_id_b)
        if node_a and node_b:
            pairs.add(canonical_pair(node_a.label, node_b.label))
    return pairs


def score_case(case: dict) -> dict:
    graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
    threshold = case.get("threshold", 0.8)
    expected = {canonical_pair(pair[0], pair[1]) for pair in case.get("expected_pairs", [])}
    predicted = predicted_pairs(graph, threshold)
    detection = f1_score(expected, predicted)

    merge_graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
    deduplicate(merge_graph, threshold=threshold)
    remaining = {normalize_text(node.label) for node in merge_graph.nodes.values()}
    expected_remaining = {normalize_text(label) for label in case.get("expected_remaining", [])}
    merge_score = 1.0 if remaining == expected_remaining else 0.0

    score = (0.70 * detection) + (0.30 * merge_score)
    return {
        "id": case["id"],
        "score": score,
        "detection": detection,
        "merge_score": merge_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate dedup autoresearch target")
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
        print("Dedup evaluation")
        for result in results:
            print(
                f"- {result['id']}: score={result['score']:.4f} "
                f"(detection={result['detection']:.4f}, merge={result['merge_score']:.4f})"
            )

    print(f"dedup_score: {overall:.4f}")


if __name__ == "__main__":
    main()
