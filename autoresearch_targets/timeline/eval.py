#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import f1_score, load_manifest, safe_div
from cortex.graph import CortexGraph
from cortex.timeline import TimelineGenerator


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def event_identity(event: dict) -> tuple[str, str]:
    return (event["label"], event["event_type"])


def ordering_accuracy(expected_events: list[dict], predicted_events: list[dict]) -> float:
    expected_order = {event_identity(event): index for index, event in enumerate(expected_events)}
    matched = [event_identity(event) for event in predicted_events if event_identity(event) in expected_order]
    if len(matched) < 2:
        return 1.0
    total = 0
    correct = 0
    for left, right in combinations(matched, 2):
        total += 1
        if expected_order[left] < expected_order[right]:
            correct += 1
    return safe_div(correct, total)


def score_case(case: dict) -> dict:
    graph = CortexGraph.from_v5_json(load_manifest(Path(case["graph_file"])))
    generator = TimelineGenerator()
    predicted = generator.generate(
        graph,
        from_date=case.get("from_date"),
        to_date=case.get("to_date"),
    )
    expected = case["expected_events"]

    expected_ids = {event_identity(event) for event in expected}
    predicted_ids = {event_identity(event) for event in predicted}
    event_score = f1_score(expected_ids, predicted_ids)

    predicted_by_id = {event_identity(event): event for event in predicted}
    timestamp_score = safe_div(
        sum(
            1
            for event in expected
            if predicted_by_id.get(event_identity(event), {}).get("timestamp") == event["timestamp"]
        ),
        len(expected),
    )
    order_score = ordering_accuracy(expected, predicted)
    score = (0.45 * event_score) + (0.25 * order_score) + (0.30 * timestamp_score)
    return {
        "id": case["id"],
        "score": score,
        "event_score": event_score,
        "order_score": order_score,
        "timestamp_score": timestamp_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate timeline autoresearch target")
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
        print("Timeline evaluation")
        for result in results:
            print(
                f"- {result['id']}: score={result['score']:.4f} "
                f"(events={result['event_score']:.4f}, order={result['order_score']:.4f}, "
                f"timestamps={result['timestamp_score']:.4f})"
            )

    print(f"timeline_score: {overall:.4f}")


if __name__ == "__main__":
    main()
