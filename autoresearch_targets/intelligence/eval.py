#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import f1_score, load_manifest, normalize_text, safe_div
from cortex.graph import CortexGraph
from cortex.intelligence import GapAnalyzer, InsightGenerator


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def canonical_edge(item: list[str]) -> tuple[str, str, str]:
    return (normalize_text(item[0]), item[1], normalize_text(item[2]))


def score_case(case: dict) -> dict:
    analyzer = GapAnalyzer()
    generator = InsightGenerator()
    kind = case["kind"]

    if kind == "stale":
        graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
        predicted = {normalize_text(node.label) for node in analyzer.stale_nodes(graph, days=180)}
        expected = {normalize_text(label) for label in case["expected_labels"]}
        score = f1_score(expected, predicted)
    elif kind == "confidence":
        graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
        predicted = {normalize_text(item["label"]) for item in analyzer.confidence_gaps(graph)}
        expected = {normalize_text(label) for label in case["expected_labels"]}
        score = f1_score(expected, predicted)
    elif kind == "relationship":
        graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
        predicted = {normalize_text(item["tag"]) for item in analyzer.relationship_gaps(graph)}
        expected = {normalize_text(tag) for tag in case["expected_tags"]}
        score = f1_score(expected, predicted)
    elif kind == "digest_contradictions":
        previous = CortexGraph.from_v5_json(load_manifest(Path(case["previous_graph_file"])))
        current = CortexGraph.from_v5_json(load_manifest(Path(case["current_graph_file"])))
        digest = generator.digest(current=current, previous=previous)
        predicted = {normalize_text(item["type"]) for item in digest["new_contradictions"]}
        expected = {normalize_text(item) for item in case["expected_types"]}
        score = f1_score(expected, predicted)
    else:
        previous = CortexGraph.from_v5_json(load_manifest(Path(case["previous_graph_file"])))
        current = CortexGraph.from_v5_json(load_manifest(Path(case["current_graph_file"])))
        digest = generator.digest(current=current, previous=previous)
        new_nodes = f1_score(
            {normalize_text(label) for label in case["expected_new_nodes"]},
            {normalize_text(item["label"]) for item in digest["new_nodes"]},
        )
        removed_nodes = f1_score(
            {normalize_text(label) for label in case["expected_removed_nodes"]},
            {normalize_text(item["label"]) for item in digest["removed_nodes"]},
        )
        new_edges = f1_score(
            {canonical_edge(item) for item in case["expected_new_edges"]},
            {
                (normalize_text(item["source"]), item["relation"], normalize_text(item["target"]))
                for item in digest["new_edges"]
            },
        )
        score = (new_nodes + removed_nodes + new_edges) / 3

    return {"id": case["id"], "score": score}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate intelligence autoresearch target")
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
        print("Intelligence evaluation")
        for result in results:
            print(f"- {result['id']}: score={result['score']:.4f}")

    print(f"intelligence_score: {overall:.4f}")


if __name__ == "__main__":
    main()
