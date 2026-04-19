"""
Cortex Edge Extraction — Phase 4 (v5.3)

Pattern-based and proximity-based edge discovery.
Applies category-pair rules to create typed edges,
plus fallback co_mentioned edges from text proximity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from cortex.graph.graph import Edge, make_edge_id

if TYPE_CHECKING:
    from cortex.graph.graph import CortexGraph


# ---------------------------------------------------------------------------
# ExtractionRule
# ---------------------------------------------------------------------------


@dataclass
class ExtractionRule:
    """A rule that maps a (source_tag, target_tag) pair to a typed edge."""

    source_tag: str
    target_tag: str
    relation: str
    confidence: float


CATEGORY_PAIR_RULES: list[ExtractionRule] = [
    ExtractionRule("technical_expertise", "active_priorities", "used_in", 0.6),
    ExtractionRule("identity", "business_context", "works_at", 0.7),
    ExtractionRule("identity", "professional_context", "holds_role", 0.7),
    ExtractionRule("relationships", "business_context", "associated_with", 0.5),
    ExtractionRule("technical_expertise", "domain_knowledge", "applied_in", 0.5),
    ExtractionRule("business_context", "market_context", "competes_in", 0.5),
    ExtractionRule("values", "active_priorities", "motivated_by", 0.4),
    ExtractionRule("constraints", "active_priorities", "constrained_by", 0.5),
]


# ---------------------------------------------------------------------------
# Rule-based extraction
# ---------------------------------------------------------------------------


def extract_edges_by_rules(
    graph: CortexGraph,
    rules: list[ExtractionRule] | None = None,
) -> list[Edge]:
    """Apply category-pair rules to discover typed edges.

    For each rule, find all nodes with source_tag and target_tag,
    then create an edge for each (source, target) pair that doesn't
    already exist in the graph.

    Returns new Edge objects (NOT yet added to graph).
    """
    if rules is None:
        rules = CATEGORY_PAIR_RULES

    now = datetime.now(timezone.utc).isoformat()

    # Build tag → node_ids index
    tag_index: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        for tag in node.tags:
            tag_index.setdefault(tag, []).append(node.id)

    # Track existing edges to avoid duplicates (both directions)
    existing: set[tuple[str, str, str]] = set()
    for e in graph.edges.values():
        existing.add((e.source_id, e.target_id, e.relation))
        existing.add((e.target_id, e.source_id, e.relation))
    seen: set[tuple[str, str, str]] = set()
    new_edges: list[Edge] = []

    for rule in rules:
        sources = tag_index.get(rule.source_tag, [])
        targets = tag_index.get(rule.target_tag, [])

        for src_id in sources:
            for tgt_id in targets:
                if src_id == tgt_id:
                    continue
                key = (src_id, tgt_id, rule.relation)
                if key in existing or key in seen:
                    continue
                seen.add(key)

                edge = Edge(
                    id=make_edge_id(src_id, tgt_id, rule.relation),
                    source_id=src_id,
                    target_id=tgt_id,
                    relation=rule.relation,
                    confidence=rule.confidence,
                    properties={"extraction": "rule_based"},
                    first_seen=now,
                    last_seen=now,
                )
                new_edges.append(edge)

    return new_edges


# ---------------------------------------------------------------------------
# Proximity-based extraction
# ---------------------------------------------------------------------------


def extract_edges_by_proximity(
    graph: CortexGraph,
    messages: list[str],
    char_distance: int = 200,
) -> list[Edge]:
    """Discover co_mentioned edges from text proximity.

    If two node labels appear within char_distance characters
    of each other in any message, create a co_mentioned edge at 0.3.

    Returns new Edge objects (NOT yet added to graph).
    """
    if not messages:
        return []

    now = datetime.now(timezone.utc).isoformat()

    # Build label → node_id mapping (escape for regex)
    label_map: dict[str, str] = {}
    patterns: list[tuple[re.Pattern, str]] = []
    for node in graph.nodes.values():
        label_lower = node.label.lower()
        if label_lower not in label_map:
            label_map[label_lower] = node.id
            try:
                pat = re.compile(r"\b" + re.escape(label_lower) + r"\b", re.IGNORECASE)
                patterns.append((pat, node.id))
            except re.error:
                continue

    # Track existing edges and discovered pairs
    existing = {(e.source_id, e.target_id) for e in graph.edges.values()} | {
        (e.target_id, e.source_id) for e in graph.edges.values()
    }
    discovered: set[tuple[str, str]] = set()

    for msg in messages:
        # Match labels in-order so proximity favors the closest local pairing
        # instead of connecting every label in a dense mention cluster.
        occurrences: list[tuple[str, int, int]] = []  # (node_id, start, end)
        for pat, nid in patterns:
            for match in pat.finditer(msg):
                occurrences.append((nid, match.start(), match.end()))
        occurrences.sort(key=lambda item: item[1])

        nearest: dict[int, tuple[int, int]] = {}
        for i, (nid_a, start_a, end_a) in enumerate(occurrences):
            best: tuple[int, int] | None = None
            for j, (nid_b, start_b, end_b) in enumerate(occurrences):
                if i == j or nid_a == nid_b:
                    continue
                distance = max(start_b - end_a, start_a - end_b, 0)
                if distance > char_distance:
                    continue
                if best is None or distance < best[0]:
                    best = (distance, j)
            if best is not None:
                nearest[i] = best

        for i, (_, _, _) in enumerate(occurrences):
            best = nearest.get(i)
            if best is None:
                continue
            _, j = best
            reverse = nearest.get(j)
            if reverse is None or reverse[1] != i:
                continue
            nid_a = occurrences[i][0]
            nid_b = occurrences[j][0]
            pair = tuple(sorted([nid_a, nid_b]))
            discovered.add(pair)  # type: ignore[arg-type]

    # Create edges for new pairs
    new_edges: list[Edge] = []
    for nid_a, nid_b in discovered:
        if (nid_a, nid_b) in existing:
            continue
        edge = Edge(
            id=make_edge_id(nid_a, nid_b, "co_mentioned"),
            source_id=nid_a,
            target_id=nid_b,
            relation="co_mentioned",
            confidence=0.3,
            properties={"extraction": "proximity"},
            first_seen=now,
            last_seen=now,
        )
        new_edges.append(edge)

    return new_edges


# ---------------------------------------------------------------------------
# Combined discovery
# ---------------------------------------------------------------------------


def discover_all_edges(
    graph: CortexGraph,
    messages: list[str] | None = None,
    rules: list[ExtractionRule] | None = None,
) -> list[Edge]:
    """Run rule-based + proximity-based extraction.

    If both produce edges for the same pair, keep the higher-confidence
    rule-based edge.
    """
    rule_edges = extract_edges_by_rules(graph, rules)

    if not messages:
        return rule_edges

    # Strong typed relations subsume raw co-mention, but weaker ones can coexist.
    rule_pairs: set[tuple[str, str]] = set()
    for e in rule_edges:
        if e.confidence >= 0.6:
            rule_pairs.add((e.source_id, e.target_id))
            rule_pairs.add((e.target_id, e.source_id))

    prox_edges = extract_edges_by_proximity(graph, messages)

    # Filter proximity edges that duplicate rule edges
    filtered = [e for e in prox_edges if (e.source_id, e.target_id) not in rule_pairs]

    return rule_edges + filtered
