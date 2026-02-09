"""
Cortex Dedup — Phase 4 (v5.3)

Graph-aware deduplication combining text similarity and neighbor overlap.
Uses existing CortexGraph.merge_nodes() for actual merging.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex.graph import CortexGraph, Node


# ---------------------------------------------------------------------------
# Similarity components
# ---------------------------------------------------------------------------

def text_similarity(label_a: str, label_b: str) -> float:
    """Text similarity between two labels using SequenceMatcher.

    Returns float in [0.0, 1.0].
    """
    a = label_a.lower().strip()
    b = label_b.lower().strip()
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def neighbor_overlap(graph: CortexGraph, node_a_id: str, node_b_id: str) -> float:
    """Jaccard similarity of neighbor sets.

    neighbors(n) = set of node_ids connected to n by any edge.
    Returns 0.0 if both have empty neighbor sets.
    """
    neighbors_a: set[str] = set()
    neighbors_b: set[str] = set()

    for edge in graph.edges.values():
        # Neighbors of A
        if edge.source_id == node_a_id:
            neighbors_a.add(edge.target_id)
        elif edge.target_id == node_a_id:
            neighbors_a.add(edge.source_id)
        # Neighbors of B
        if edge.source_id == node_b_id:
            neighbors_b.add(edge.target_id)
        elif edge.target_id == node_b_id:
            neighbors_b.add(edge.source_id)

    # Remove each other from neighbor sets (they might be neighbors)
    neighbors_a.discard(node_b_id)
    neighbors_b.discard(node_a_id)

    union = neighbors_a | neighbors_b
    if not union:
        return 0.0

    intersection = neighbors_a & neighbors_b
    return len(intersection) / len(union)


def combined_similarity(
    graph: CortexGraph,
    node_a: Node,
    node_b: Node,
    text_weight: float = 0.7,
    neighbor_weight: float = 0.3,
) -> float:
    """Weighted combination of text similarity and neighbor overlap.

    similarity = text_weight * text_sim + neighbor_weight * neighbor_sim
    """
    t_sim = text_similarity(node_a.label, node_b.label)
    n_sim = neighbor_overlap(graph, node_a.id, node_b.id)
    return text_weight * t_sim + neighbor_weight * n_sim


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def find_duplicates(
    graph: CortexGraph,
    threshold: float = 0.80,
) -> list[tuple[str, str, float]]:
    """Find candidate duplicate node pairs.

    Pre-filter: only compare nodes that share at least one tag.
    Returns [(node_id_a, node_id_b, similarity)] sorted by similarity desc.
    """
    nodes = list(graph.nodes.values())
    results: list[tuple[str, str, float]] = []

    for i, a in enumerate(nodes):
        a_tags = set(a.tags)
        for b in nodes[i + 1:]:
            # Pre-filter: must share at least one tag
            if not a_tags & set(b.tags):
                continue

            sim = combined_similarity(graph, a, b)
            if sim >= threshold:
                results.append((a.id, b.id, sim))

    results.sort(key=lambda x: x[2], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Deduplicate
# ---------------------------------------------------------------------------

def deduplicate(
    graph: CortexGraph,
    threshold: float = 0.80,
) -> list[tuple[str, str]]:
    """Find and merge duplicate nodes.

    Greedy: highest similarity first. If a node was already merged, skip.
    Returns list of (survivor_id, merged_id) tuples.
    """
    candidates = find_duplicates(graph, threshold)
    merged_away: set[str] = set()
    results: list[tuple[str, str]] = []

    for nid_a, nid_b, _sim in candidates:
        if nid_a in merged_away or nid_b in merged_away:
            continue
        if graph.get_node(nid_a) is None or graph.get_node(nid_b) is None:
            continue

        graph.merge_nodes(nid_a, nid_b)
        merged_away.add(nid_b)
        results.append((nid_a, nid_b))

    return results
