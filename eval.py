#!/usr/bin/env python3
"""
Cortex Autoresearch — Evaluator
Computes extraction_score across the labeled corpus.

Usage:
  python eval.py               # Full eval with per-test breakdown
  python eval.py --quiet       # Score only (for agent loops)
  python eval.py --test NAME   # Single test case
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CORPUS_DIR = Path("corpus")
MANIFEST = CORPUS_DIR / "manifest.json"


# ─── Extraction Runner ────────────────────────────────────────────────────────

def run_cortex_extract(input_path: Path) -> dict | None:
    """Run `cortex extract` and return parsed output, or None on failure."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = Path(tmp.name)

    try:
        result = subprocess.run(
            ["cortex", "extract", str(input_path), "-o", str(out_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        if not out_path.exists():
            return None
        return json.loads(out_path.read_text())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None
    finally:
        out_path.unlink(missing_ok=True)


# ─── Scoring Components ───────────────────────────────────────────────────────

def score_recall(extracted: dict, ground_truth: dict) -> tuple[float, dict]:
    """
    Entity recall: fraction of known ground-truth entities recovered.
    Searches across all node labels and values in the extracted graph.
    Returns (score, detail).
    """
    nodes = extracted.get("nodes", [])
    # Build a flat searchable string from all node content
    node_text = " ".join(
        str(n.get("label", "")) + " " + str(n.get("value", "")) + " " + str(n.get("category", ""))
        for n in nodes
    ).lower()

    hits, misses = [], []
    total = 0

    for category, items in ground_truth.items():
        # Skip metadata fields that aren't extraction targets
        if category in ("notes", "deduplication_challenge", "filler_not_preferences", "contradictions"):
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, str):
                continue
            total += 1
            # Fuzzy match: check if core terms from the item appear in extracted nodes
            core_terms = [t for t in item.lower().split() if len(t) > 3]
            matched = any(term in node_text for term in core_terms) if core_terms else False
            if matched:
                hits.append(item)
            else:
                misses.append(item)

    score = len(hits) / total if total > 0 else 1.0
    return score, {"hits": hits, "misses": misses, "total": total}


def score_deduplication(extracted: dict) -> tuple[float, dict]:
    """
    Penalize duplicate nodes. A clean graph has no redundant entries.
    Near-duplicates (case, punctuation) count as duplicates.
    Returns (score, detail).
    """
    nodes = extracted.get("nodes", [])
    if not nodes:
        return 1.0, {"unique": 0, "total": 0, "duplicates": []}

    labels = [str(n.get("label", "")).lower().strip().rstrip("s") for n in nodes]
    seen, duplicates = set(), []

    for label in labels:
        if label in seen:
            duplicates.append(label)
        seen.add(label)

    unique_ratio = len(seen) / len(labels)
    return unique_ratio, {
        "unique": len(seen),
        "total": len(labels),
        "duplicates": duplicates[:5],  # Cap for readability
    }


def score_false_positives(extracted: dict, ground_truth: dict) -> tuple[float, dict]:
    """
    For test cases with filler_not_preferences: penalize extracting
    speculative mentions as confirmed entities.
    Returns (score, detail).
    """
    filler = ground_truth.get("filler_not_preferences", [])
    if not filler:
        return 1.0, {"applicable": False}

    nodes = extracted.get("nodes", [])
    node_text = " ".join(
        str(n.get("label", "")) + " " + str(n.get("value", ""))
        for n in nodes
    ).lower()

    false_positives = []
    for item in filler:
        # Extract just the technology name (before parenthetical)
        term = item.split("(")[0].strip().lower()
        if term and term in node_text:
            false_positives.append(item)

    penalty = len(false_positives) / len(filler)
    score = 1.0 - penalty
    return score, {"false_positives": false_positives, "checked": filler}


def score_contradiction_detection(extracted: dict, test_case: dict) -> tuple[float, dict]:
    """
    For seeded contradiction tests: reward detection of known conflicts.
    Returns (score, detail).
    """
    if not test_case.get("has_seeded_contradictions"):
        return 1.0, {"applicable": False}

    contradictions_found = extracted.get("contradictions", [])
    detected = len(contradictions_found) > 0

    return (1.0 if detected else 0.0), {
        "detected": detected,
        "contradiction_count": len(contradictions_found),
    }


# ─── Per-Test Scorer ──────────────────────────────────────────────────────────

def score_test(test_case: dict, quiet: bool = False) -> float:
    input_path = CORPUS_DIR / test_case["input_file"]
    gt_path = CORPUS_DIR / test_case["ground_truth_file"]
    weights = test_case.get("weights", {"recall": 0.5, "dedup": 0.25, "contradiction_detection": 0.25})

    ground_truth = json.loads(gt_path.read_text())
    extracted = run_cortex_extract(input_path)

    if extracted is None:
        if not quiet:
            print(f"  FAIL (extraction error) — score: 0.0000")
        return 0.0

    recall_score, recall_detail = score_recall(extracted, ground_truth)
    dedup_score, dedup_detail = score_deduplication(extracted)
    fp_score, fp_detail = score_false_positives(extracted, ground_truth)
    contradiction_score, contradiction_detail = score_contradiction_detection(extracted, test_case)

    # Blend dedup and false-positive penalty into the dedup component
    combined_dedup = (dedup_score + fp_score) / 2

    final = (
        weights["recall"] * recall_score
        + weights["dedup"] * combined_dedup
        + weights["contradiction_detection"] * contradiction_score
    )

    if not quiet:
        print(f"  recall:        {recall_score:.4f}  (hits {recall_detail['hits'][:3]}...)")
        print(f"  dedup:         {dedup_score:.4f}  ({dedup_detail['unique']}/{dedup_detail['total']} unique)")
        print(f"  false_pos:     {fp_score:.4f}")
        print(f"  contradiction: {contradiction_score:.4f}")
        print(f"  → score:       {final:.4f}")

    return final


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cortex autoresearch evaluator")
    parser.add_argument("--quiet", action="store_true", help="Print score only")
    parser.add_argument("--test", type=str, help="Run single test case by name")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print("ERROR: corpus/manifest.json not found. Run generate_corpus.py first.")
        sys.exit(1)

    manifest = json.loads(MANIFEST.read_text())
    tests = manifest["tests"]

    if args.test:
        tests = [t for t in tests if t["name"] == args.test]
        if not tests:
            print(f"ERROR: Test '{args.test}' not found in manifest.")
            sys.exit(1)

    scores = []
    for test in tests:
        if not args.quiet:
            print(f"\n[{test['name']}]  ({test['description']})")
        score = score_test(test, quiet=args.quiet)
        scores.append(score)

    final = sum(scores) / len(scores) if scores else 0.0

    if args.quiet:
        print(f"{final:.4f}")
    else:
        print(f"\n{'─'*50}")
        print(f"extraction_score: {final:.4f}  ({len(scores)} tests)")
        target = manifest["scoring"]["target"]
        gap = target - final
        if gap > 0:
            print(f"Target:           {target:.4f}  (gap: {gap:.4f})")
        else:
            print(f"Target {target:.4f} REACHED ✓")

    return final


if __name__ == "__main__":
    main()
