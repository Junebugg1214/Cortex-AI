"""
Cortex Co-Occurrence — Phase 4 (v5.3)

Tiered co-occurrence edge discovery.
PMI for >= 500 messages, frequency for 100-499, strict for < 100.
Minimum co-occurrence count of 3 always required.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from cortex.graph import Edge, make_edge_id

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def count_cooccurrences(
    messages: list[str],
    node_labels: list[str],
) -> dict[tuple[str, str], int]:
    """Count how many messages each pair of labels co-occurs in.

    A label co-occurs in a message if it appears as a case-insensitive
    substring. Returns {(label_a, label_b): count} with sorted pairs.
    """
    counts: dict[tuple[str, str], int] = {}
    # Pre-compile word-boundary patterns to avoid substring false positives
    # (e.g. "AI" matching "waiting", "Go" matching "going")
    label_patterns = []
    for label in node_labels:
        try:
            pat = re.compile(r"\b" + re.escape(label.lower()) + r"\b", re.IGNORECASE)
        except re.error:
            pat = None
        label_patterns.append(pat)

    for msg in messages:
        # Find which labels appear in this message
        present: list[str] = []
        for i, pat in enumerate(label_patterns):
            if pat is not None and pat.search(msg):
                present.append(node_labels[i])

        # Count all pairs
        for i, a in enumerate(present):
            for b in present[i + 1:]:
                pair = tuple(sorted([a, b]))
                counts[pair] = counts.get(pair, 0) + 1  # type: ignore[index]

    return counts


def label_message_counts(
    messages: list[str],
    node_labels: list[str],
) -> dict[str, int]:
    """Count how many messages each label appears in."""
    counts: dict[str, int] = {label: 0 for label in node_labels}
    # Pre-compile word-boundary patterns to match whole words only
    label_patterns: list[tuple[str, re.Pattern | None]] = []
    for label in node_labels:
        try:
            pat = re.compile(r"\b" + re.escape(label.lower()) + r"\b", re.IGNORECASE)
        except re.error:
            pat = None
        label_patterns.append((label, pat))

    for msg in messages:
        for label, pat in label_patterns:
            if pat is not None and pat.search(msg):
                counts[label] += 1

    return counts


# ---------------------------------------------------------------------------
# PMI edges
# ---------------------------------------------------------------------------

def pmi_edges(
    cooccurrences: dict[tuple[str, str], int],
    label_counts: dict[str, int],
    total_messages: int,
    threshold: float = 2.0,
    min_count: int = 3,
) -> list[tuple[str, str, float]]:
    """Pointwise Mutual Information for label pairs.

    PMI(a,b) = log2(P(a,b) / (P(a) * P(b)))

    Returns [(label_a, label_b, pmi_score)] where pmi >= threshold
    and co-occurrence count >= min_count. Sorted by PMI descending.
    """
    if total_messages == 0:
        return []

    results: list[tuple[str, str, float]] = []

    for (a, b), count in cooccurrences.items():
        if count < min_count:
            continue

        p_ab = count / total_messages
        p_a = label_counts.get(a, 0) / total_messages
        p_b = label_counts.get(b, 0) / total_messages

        if p_a == 0 or p_b == 0:
            continue

        pmi = math.log2(p_ab / (p_a * p_b))
        if pmi >= threshold:
            results.append((a, b, pmi))

    results.sort(key=lambda x: x[2], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Frequency edges
# ---------------------------------------------------------------------------

def frequency_edges(
    cooccurrences: dict[tuple[str, str], int],
    total_messages: int,
    min_count: int = 3,
    min_ratio: float = 0.05,
) -> list[tuple[str, str, float]]:
    """Frequency-based edge discovery.

    Include pairs where count >= min_count AND count/total >= min_ratio.
    Confidence = min(count / (total * 0.1), 1.0).

    Returns [(label_a, label_b, confidence)].
    """
    if total_messages == 0:
        return []

    results: list[tuple[str, str, float]] = []

    for (a, b), count in cooccurrences.items():
        if count < min_count:
            continue
        ratio = count / total_messages
        if ratio < min_ratio:
            continue
        confidence = min(count / (total_messages * 0.1), 1.0)
        results.append((a, b, confidence))

    results.sort(key=lambda x: x[2], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Tiered dispatch
# ---------------------------------------------------------------------------

def discover_edges(
    messages: list[str],
    graph: CortexGraph,
) -> list[Edge]:
    """Tiered co-occurrence edge discovery.

    >= 500 messages: PMI (threshold=2.0, min_count=3)
    >= 100 messages: frequency (min_count=3, min_ratio=0.02)
    <  100 messages: frequency (min_count=3, min_ratio=0.05)

    Skips pairs that already have edges in the graph.
    Edge relation: "co_occurs", confidence capped at 0.8.
    """
    node_labels = [n.label for n in graph.nodes.values()]
    if not node_labels or not messages:
        return []

    cooc = count_cooccurrences(messages, node_labels)
    total = len(messages)

    if total >= 500:
        label_counts = label_message_counts(messages, node_labels)
        pairs = pmi_edges(cooc, label_counts, total, threshold=2.0, min_count=3)
        # Normalize PMI to confidence: pmi / 5.0, capped at 0.8
        scored = [(a, b, min(score / 5.0, 0.8)) for a, b, score in pairs]
    elif total >= 100:
        scored = frequency_edges(cooc, total, min_count=3, min_ratio=0.02)
    else:
        scored = frequency_edges(cooc, total, min_count=3, min_ratio=0.05)

    # Build label → node_id mapping
    label_to_id: dict[str, str] = {}
    for node in graph.nodes.values():
        label_to_id[node.label] = node.id

    # Track existing edges
    existing = {
        (e.source_id, e.target_id) for e in graph.edges.values()
    } | {
        (e.target_id, e.source_id) for e in graph.edges.values()
    }

    now = datetime.now(timezone.utc).isoformat()
    new_edges: list[Edge] = []

    for label_a, label_b, confidence in scored:
        nid_a = label_to_id.get(label_a)
        nid_b = label_to_id.get(label_b)
        if nid_a is None or nid_b is None:
            continue
        if (nid_a, nid_b) in existing:
            continue

        # Cap confidence at 0.8 for co-occurrence (circumstantial)
        conf = min(confidence, 0.8)
        edge = Edge(
            id=make_edge_id(nid_a, nid_b, "co_occurs"),
            source_id=nid_a,
            target_id=nid_b,
            relation="co_occurs",
            confidence=conf,
            properties={"extraction": "cooccurrence"},
            first_seen=now,
            last_seen=now,
        )
        new_edges.append(edge)
        existing.add((nid_a, nid_b))

    return new_edges
