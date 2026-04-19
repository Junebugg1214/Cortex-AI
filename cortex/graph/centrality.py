"""
Cortex Centrality — Phase 4 (v5.3)

Right-sized centrality algorithms for 50-200 node knowledge graphs.
Degree centrality by default, PageRank for >= 200 nodes.
Pure Python stdlib — no external dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cortex.graph.graph import CortexGraph

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PAGERANK_THRESHOLD = 200  # Minimum nodes to justify PageRank
_CENTRALITY_MIN_NODES = 20  # Minimum nodes for confidence boost
_CENTRALITY_BOOST_MAX = 0.1  # Maximum confidence boost for top-decile


# ---------------------------------------------------------------------------
# Degree centrality
# ---------------------------------------------------------------------------


def compute_degree_centrality(graph: CortexGraph) -> dict[str, float]:
    """Normalized degree centrality: degree(node) / (n - 1).

    Treats the graph as undirected — each edge increments the degree of
    both its source and target nodes.  Returns empty dict if graph has
    < 2 nodes.
    """
    n = len(graph.nodes)
    if n < 2:
        return {nid: 0.0 for nid in graph.nodes}

    degrees: dict[str, int] = {nid: 0 for nid in graph.nodes}
    for edge in graph.edges.values():
        if edge.source_id in degrees:
            degrees[edge.source_id] += 1
        if edge.target_id in degrees:
            degrees[edge.target_id] += 1

    denom = n - 1
    return {nid: deg / denom for nid, deg in degrees.items()}


# ---------------------------------------------------------------------------
# PageRank (power iteration)
# ---------------------------------------------------------------------------


def compute_pagerank(
    graph: CortexGraph,
    damping: float = 0.85,
    iterations: int = 100,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    """Pure Python PageRank using power iteration.

    Iterates until convergence (L1 norm < tolerance) or max iterations.
    Scores sum to ~1.0.
    """
    nodes = list(graph.nodes.keys())
    n = len(nodes)
    if n == 0:
        return {}

    # Build adjacency: incoming edges per node and out-degree
    incoming: dict[str, list[str]] = {nid: [] for nid in nodes}
    out_degree: dict[str, int] = {nid: 0 for nid in nodes}

    for edge in graph.edges.values():
        src, tgt = edge.source_id, edge.target_id
        if src in incoming and tgt in incoming:
            incoming[tgt].append(src)
            out_degree[src] += 1

    # Identify dangling nodes (no outgoing edges)
    dangling = [nid for nid in nodes if out_degree[nid] == 0]

    # Initialize scores uniformly
    scores = {nid: 1.0 / n for nid in nodes}
    base = (1.0 - damping) / n

    for _ in range(iterations):
        # Dangling node contribution: distributed evenly to all nodes
        dangling_sum = sum(scores[nid] for nid in dangling)
        dangling_contrib = damping * dangling_sum / n

        new_scores: dict[str, float] = {}
        for nid in nodes:
            rank_sum = 0.0
            for src in incoming[nid]:
                if out_degree[src] > 0:
                    rank_sum += scores[src] / out_degree[src]
            new_scores[nid] = base + dangling_contrib + damping * rank_sum

        # Check convergence
        diff = sum(abs(new_scores[nid] - scores[nid]) for nid in nodes)
        scores = new_scores
        if diff < tolerance:
            break

    return scores


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def compute_centrality(graph: CortexGraph) -> dict[str, float]:
    """Degree centrality for < 200 nodes, PageRank for >= 200."""
    if len(graph.nodes) >= _PAGERANK_THRESHOLD:
        return compute_pagerank(graph)
    return compute_degree_centrality(graph)


# ---------------------------------------------------------------------------
# Confidence boost
# ---------------------------------------------------------------------------


def apply_centrality_boost(
    graph: CortexGraph,
    centrality: dict[str, float],
) -> None:
    """Boost confidence of top-decile nodes by up to +0.1.

    Only applies if >= 20 nodes. Modifies nodes in-place.
    Stores centrality score in node.properties["centrality"].
    Caps confidence at 1.0.
    """
    n = len(graph.nodes)

    # Store centrality scores regardless of node count
    for nid, score in centrality.items():
        node = graph.get_node(nid)
        if node is not None:
            node.properties["centrality"] = round(score, 6)

    if n < _CENTRALITY_MIN_NODES:
        return

    # Sort by centrality descending
    ranked = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
    decile_size = max(1, n // 10)

    for rank, (nid, _score) in enumerate(ranked[:decile_size]):
        node = graph.get_node(nid)
        if node is None:
            continue
        # Linear interpolation: rank 0 → full boost, last in decile → 10% of boost
        fraction = 1.0 - (rank / decile_size) if decile_size > 1 else 1.0
        boost = _CENTRALITY_BOOST_MAX * fraction
        node.confidence = min(node.confidence + boost, 1.0)
