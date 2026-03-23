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


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def rank_of_expected(results: list[dict], expected_label: str) -> int | None:
    want = normalize_text(expected_label)
    for index, item in enumerate(results, start=1):
        node = item["node"]
        label = normalize_text(node.label if hasattr(node, "label") else node.get("label", ""))
        if label == want:
            return index
    return None


def score_case(case: dict) -> dict:
    graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
    results = graph.semantic_search(case["query"], limit=5)
    rank = rank_of_expected(results, case["expected_top"])
    mrr = 0.0 if rank is None else 1.0 / rank
    hit1 = 1.0 if rank == 1 else 0.0
    hit3 = 1.0 if rank is not None and rank <= 3 else 0.0
    score = (0.40 * mrr) + (0.30 * hit1) + (0.30 * hit3)
    return {"id": case["id"], "score": score, "rank": rank, "mrr": mrr, "hit1": hit1, "hit3": hit3}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate search autoresearch target")
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
        print("Search evaluation")
        for result in results:
            rank = "-" if result["rank"] is None else str(result["rank"])
            print(
                f"- {result['id']}: score={result['score']:.4f} "
                f"(rank={rank}, mrr={result['mrr']:.4f}, hit1={result['hit1']:.0f}, hit3={result['hit3']:.0f})"
            )

    print(f"search_score: {overall:.4f}")


if __name__ == "__main__":
    main()
