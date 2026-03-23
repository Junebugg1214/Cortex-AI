#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import flatten_topic_text, load_manifest, normalize_text, safe_div
from cortex.coding import aggregate_sessions, enrich_session, parse_claude_code_session, session_to_context


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "corpus" / "manifest.json"


def load_records(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def category_topics(context: dict, category: str) -> list[dict]:
    return list(context.get("categories", {}).get(category, []))


def topic_hit(expected: str, topics: list[dict]) -> bool:
    wanted = normalize_text(expected)
    for topic in topics:
        if normalize_text(str(topic.get("topic", ""))) == wanted:
            return True
        if wanted and wanted in flatten_topic_text(topic):
            return True
    return False


def text_hit(expected: str, topics: list[dict]) -> bool:
    wanted = normalize_text(expected)
    for topic in topics:
        if wanted and wanted in flatten_topic_text(topic):
            return True
    return False


def score_case(case: dict) -> dict:
    sessions = [parse_claude_code_session(load_records(Path(path))) for path in case["session_files"]]
    session = aggregate_sessions(sessions) if len(sessions) > 1 else sessions[0]
    if case.get("enrich"):
        enrich_session(session)
    context = session_to_context(session)

    expected_topics = case.get("expected_topics", {})
    topic_checks = []
    for category, expected in expected_topics.items():
        topics = category_topics(context, category)
        for item in expected:
            topic_checks.append(topic_hit(item, topics))
    topic_recall = safe_div(sum(topic_checks), len(topic_checks))

    expected_text = case.get("expected_text", {})
    text_checks = []
    for category, expected in expected_text.items():
        topics = category_topics(context, category)
        for item in expected:
            text_checks.append(text_hit(item, topics))
    text_recall = safe_div(sum(text_checks), len(text_checks))

    all_topics = [topic for topics in context.get("categories", {}).values() for topic in topics]
    forbidden = case.get("forbidden_topics", [])
    forbidden_hits = 0
    for unwanted in forbidden:
        if any(text_hit(unwanted, [topic]) for topic in all_topics):
            forbidden_hits += 1
    precision = 1.0 if not forbidden else max(0.0, 1.0 - (forbidden_hits / len(forbidden)))

    score = (0.55 * topic_recall) + (0.25 * text_recall) + (0.20 * precision)
    return {
        "id": case["id"],
        "score": score,
        "topic_recall": topic_recall,
        "text_recall": text_recall,
        "precision": precision,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate extract-coding autoresearch target")
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
        print("Extract-coding evaluation")
        for result in results:
            print(
                f"- {result['id']}: score={result['score']:.4f} "
                f"(topic_recall={result['topic_recall']:.4f}, "
                f"text_recall={result['text_recall']:.4f}, precision={result['precision']:.4f})"
            )

    print(f"coding_extraction_score: {overall:.4f}")


if __name__ == "__main__":
    main()
