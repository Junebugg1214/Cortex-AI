#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import f1_score, load_manifest, normalize_text, safe_div
from cortex.contradictions import ContradictionEngine
from cortex.graph import CortexGraph


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def expected_key(item: dict) -> tuple[str, str]:
    return (item["type"], normalize_text(item["label"]))


def predicted_key(item) -> tuple[str, str]:
    return (item.type, normalize_text(item.node_label or item.description))


def score_case(case: dict) -> dict:
    graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
    engine = ContradictionEngine()
    predicted_items = engine.detect_all(graph)

    predicted_counter = Counter(predicted_key(item) for item in predicted_items)
    expected_counter = Counter(expected_key(item) for item in case.get("expected", []))
    true_positive = sum(min(predicted_counter[key], expected_counter[key]) for key in expected_counter)

    if not expected_counter and not predicted_counter:
        detection = 1.0
    elif not expected_counter or not predicted_counter:
        detection = 0.0
    else:
        precision = safe_div(true_positive, sum(predicted_counter.values()))
        recall = safe_div(true_positive, sum(expected_counter.values()))
        detection = 0.0 if precision + recall == 0 else (2 * precision * recall / (precision + recall))

    if not case.get("expected"):
        resolution = 1.0 if not predicted_items else 0.0
    else:
        predicted_resolutions = {predicted_key(item): item.resolution for item in predicted_items}
        matches = 0
        for item in case["expected"]:
            if predicted_resolutions.get(expected_key(item)) == item["resolution"]:
                matches += 1
        resolution = safe_div(matches, len(case["expected"]))

    score = (0.80 * detection) + (0.20 * resolution)
    return {
        "id": case["id"],
        "score": score,
        "detection": detection,
        "resolution": resolution,
        "predicted": sum(predicted_counter.values()),
        "expected": sum(expected_counter.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate contradictions autoresearch target")
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
        print("Contradictions evaluation")
        for result in results:
            print(
                f"- {result['id']}: score={result['score']:.4f} "
                f"(detection={result['detection']:.4f}, resolution={result['resolution']:.4f}, "
                f"expected={result['expected']}, predicted={result['predicted']})"
            )

    print(f"contradictions_score: {overall:.4f}")


if __name__ == "__main__":
    main()
