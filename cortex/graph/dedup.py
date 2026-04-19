"""
Cortex Dedup — Phase 4 (v5.3)

Graph-aware deduplication combining text similarity and neighbor overlap.
Uses existing CortexGraph.merge_nodes() for actual merging.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex.graph.graph import CortexGraph, Node


# ---------------------------------------------------------------------------
# Similarity components
# ---------------------------------------------------------------------------


_ALIAS_MAP = {
    "js": "javascript",
    "k8s": "kubernetes",
    "postgres": "postgresql",
}


def _canonicalize_label(label: str) -> tuple[str, str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    canonical = " ".join(_ALIAS_MAP.get(token, token) for token in normalized.split())
    base = re.sub(r"(?:\s+v?\d+(?:\s+\d+)*)+$", "", canonical).strip() or canonical
    return canonical, base


def text_similarity(label_a: str, label_b: str) -> float:
    """Text similarity between two labels using SequenceMatcher.

    Returns float in [0.0, 1.0].
    """
    a, a_base = _canonicalize_label(label_a)
    b, b_base = _canonicalize_label(label_b)
    if a == b:
        return 1.0
    if a_base == b_base:
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
        for b in nodes[i + 1 :]:
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

    Computes the transitive closure of duplicate pairs, then compacts each
    equivalence class into one canonical node. Canonical selection prefers the
    highest confidence node, then the earliest first_seen timestamp.
    Returns list of (survivor_id, merged_id) tuples.
    """
    candidates = find_duplicates(graph, threshold)
    if not candidates:
        return []

    parent: dict[str, str] = {}

    def find(node_id: str) -> str:
        parent.setdefault(node_id, node_id)
        if parent[node_id] != node_id:
            parent[node_id] = find(parent[node_id])
        return parent[node_id]

    def union(node_id_a: str, node_id_b: str) -> None:
        root_a = find(node_id_a)
        root_b = find(node_id_b)
        if root_a != root_b:
            parent[root_b] = root_a

    for nid_a, nid_b, _sim in candidates:
        union(nid_a, nid_b)

    classes: dict[str, list[str]] = {}
    for node_id in parent:
        classes.setdefault(find(node_id), []).append(node_id)

    results: list[tuple[str, str]] = []

    def canonical_sort_key(node_id: str) -> tuple[float, str, str]:
        node = graph.nodes[node_id]
        first_seen = node.first_seen or "9999-12-31T23:59:59.999999+00:00"
        return (-node.confidence, first_seen, node_id)

    for node_ids in classes.values():
        live_node_ids = [node_id for node_id in node_ids if graph.get_node(node_id) is not None]
        if len(live_node_ids) < 2:
            continue

        canonical_id = min(live_node_ids, key=canonical_sort_key)
        for merged_id in sorted(node_id for node_id in live_node_ids if node_id != canonical_id):
            if graph.get_node(merged_id) is None:
                continue
            graph.merge_nodes(canonical_id, merged_id)
            results.append((canonical_id, merged_id))

    return results
