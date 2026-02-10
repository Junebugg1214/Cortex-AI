"""
Cortex Visualization Layout — Phase 6 (v6.0)

Fruchterman-Reingold force-directed layout in pure Python.
Optional numpy fast path for ~10x speedup on large graphs.
Pure Python stdlib — no external dependencies for core path.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

LayoutResult = dict[str, tuple[float, float]]  # node_id -> (x, y)


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def _layout_cache_key(node_ids: list[str], edge_tuples: list[tuple[str, str]]) -> str:
    """Deterministic hash of graph structure for cache invalidation."""
    data = json.dumps({"n": sorted(node_ids), "e": sorted(edge_tuples)}, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Adjacency builder
# ---------------------------------------------------------------------------

def _build_adjacency(node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, set[str]]:
    """Build undirected adjacency from node IDs and edge tuples."""
    adj: dict[str, set[str]] = {nid: set() for nid in node_ids}
    for src, tgt in edges:
        if src in adj and tgt in adj:
            adj[src].add(tgt)
            adj[tgt].add(src)
    return adj


# ---------------------------------------------------------------------------
# Pure Python Fruchterman-Reingold
# ---------------------------------------------------------------------------

def _fr_pure(
    adj: dict[str, set[str]],
    node_list: list[str],
    iterations: int,
    width: float,
    height: float,
    seed: int | None,
    progress: Callable[[int, int], None] | None,
) -> LayoutResult:
    """Pure Python FR layout. Always available."""
    n = len(node_list)
    if n == 0:
        return {}
    if n == 1:
        return {node_list[0]: (width / 2, height / 2)}

    rng = random.Random(seed)
    area = width * height
    k = math.sqrt(area / n) if area > 0 else 1.0
    temp = width / 10.0 if width > 0 else 1.0

    # Initialize random positions
    pos: dict[str, list[float]] = {
        nid: [rng.uniform(0.1 * width, 0.9 * width),
              rng.uniform(0.1 * height, 0.9 * height)]
        for nid in node_list
    }

    for iteration in range(iterations):
        disp: dict[str, list[float]] = {nid: [0.0, 0.0] for nid in node_list}

        # Repulsive forces (all pairs)
        for i in range(n):
            for j in range(i + 1, n):
                ni, nj = node_list[i], node_list[j]
                dx = pos[ni][0] - pos[nj][0]
                dy = pos[ni][1] - pos[nj][1]
                dist = max(math.sqrt(dx * dx + dy * dy), 0.01)
                force = (k * k) / dist
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                disp[ni][0] += fx
                disp[ni][1] += fy
                disp[nj][0] -= fx
                disp[nj][1] -= fy

        # Attractive forces (edges)
        for ni in node_list:
            for nj in adj.get(ni, set()):
                if ni >= nj:
                    continue  # process each edge once
                dx = pos[ni][0] - pos[nj][0]
                dy = pos[ni][1] - pos[nj][1]
                dist = max(math.sqrt(dx * dx + dy * dy), 0.01)
                force = (dist * dist) / k
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                disp[ni][0] -= fx
                disp[ni][1] -= fy
                disp[nj][0] += fx
                disp[nj][1] += fy

        # Apply displacements capped by temperature
        for nid in node_list:
            dx, dy = disp[nid]
            dist = max(math.sqrt(dx * dx + dy * dy), 0.01)
            scale = min(dist, temp) / dist
            pos[nid][0] += dx * scale
            pos[nid][1] += dy * scale
            # Clamp to bounds
            pos[nid][0] = max(0.0, min(width, pos[nid][0]))
            pos[nid][1] = max(0.0, min(height, pos[nid][1]))

        # Cool temperature (linear schedule)
        temp = (width / 10.0) * (1.0 - (iteration + 1) / iterations)

        if progress:
            progress(iteration + 1, iterations)

    return {nid: (pos[nid][0], pos[nid][1]) for nid in node_list}


# ---------------------------------------------------------------------------
# Numpy-accelerated Fruchterman-Reingold
# ---------------------------------------------------------------------------

def _fr_numpy(
    adj: dict[str, set[str]],
    node_list: list[str],
    iterations: int,
    width: float,
    height: float,
    seed: int | None,
    progress: Callable[[int, int], None] | None,
) -> LayoutResult:
    """Numpy-accelerated FR layout. ~10x faster for large graphs."""
    import numpy as np  # type: ignore[import-untyped]

    n = len(node_list)
    if n == 0:
        return {}
    if n == 1:
        return {node_list[0]: (width / 2, height / 2)}

    rng = np.random.RandomState(seed)
    area = width * height
    k = np.sqrt(area / n) if area > 0 else 1.0
    temp = width / 10.0 if width > 0 else 1.0

    # Node index mapping
    idx = {nid: i for i, nid in enumerate(node_list)}

    # Build edge arrays
    edges_src: list[int] = []
    edges_tgt: list[int] = []
    for ni in node_list:
        for nj in adj.get(ni, set()):
            if ni < nj:
                edges_src.append(idx[ni])
                edges_tgt.append(idx[nj])
    edge_src = np.array(edges_src, dtype=np.int64)
    edge_tgt = np.array(edges_tgt, dtype=np.int64)

    # Initialize positions
    pos = rng.uniform(
        [0.1 * width, 0.1 * height],
        [0.9 * width, 0.9 * height],
        size=(n, 2),
    )

    for iteration in range(iterations):
        # Pairwise repulsion
        delta = pos[:, np.newaxis, :] - pos[np.newaxis, :, :]  # (n, n, 2)
        dist = np.sqrt((delta ** 2).sum(axis=2))  # (n, n)
        np.clip(dist, 0.01, None, out=dist)
        force_mag = (k * k) / dist  # (n, n)
        np.fill_diagonal(force_mag, 0.0)
        # Force direction
        force = delta * (force_mag / dist)[:, :, np.newaxis]  # (n, n, 2)
        disp = force.sum(axis=1)  # (n, 2) — net repulsion

        # Attractive forces along edges
        if len(edge_src) > 0:
            edge_delta = pos[edge_src] - pos[edge_tgt]  # (E, 2)
            edge_dist = np.sqrt((edge_delta ** 2).sum(axis=1))  # (E,)
            np.clip(edge_dist, 0.01, None, out=edge_dist)
            edge_force_mag = (edge_dist ** 2) / k  # (E,)
            edge_force = edge_delta * (edge_force_mag / edge_dist)[:, np.newaxis]
            np.add.at(disp, edge_src, -edge_force)
            np.add.at(disp, edge_tgt, edge_force)

        # Apply displacement capped by temperature
        disp_mag = np.sqrt((disp ** 2).sum(axis=1))  # (n,)
        np.clip(disp_mag, 0.01, None, out=disp_mag)
        scale = np.minimum(disp_mag, temp) / disp_mag
        pos += disp * scale[:, np.newaxis]

        # Clamp to bounds
        np.clip(pos[:, 0], 0.0, width, out=pos[:, 0])
        np.clip(pos[:, 1], 0.0, height, out=pos[:, 1])

        # Cool temperature (linear schedule)
        temp = (width / 10.0) * (1.0 - (iteration + 1) / iterations)

        if progress:
            progress(iteration + 1, iterations)

    return {node_list[i]: (float(pos[i, 0]), float(pos[i, 1])) for i in range(n)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fruchterman_reingold(
    graph: CortexGraph,
    iterations: int = 50,
    width: float = 1.0,
    height: float = 1.0,
    seed: int | None = 42,
    max_nodes: int = 200,
    progress: Callable[[int, int], None] | None = None,
) -> LayoutResult:
    """Compute 2D positions for graph nodes using FR layout.

    Returns dict of {node_id: (x, y)} in [0, width] x [0, height].
    If graph has more than max_nodes, selects top N by degree centrality.
    Results are cached on the graph object for repeated calls.
    """
    if not graph.nodes:
        return {}

    # Select nodes if over limit
    node_ids = list(graph.nodes.keys())
    if len(node_ids) > max_nodes:
        from cortex.centrality import compute_degree_centrality
        scores = compute_degree_centrality(graph)
        node_ids = sorted(scores, key=lambda nid: scores.get(nid, 0), reverse=True)[:max_nodes]
    node_set = set(node_ids)

    # Build edge tuples (only edges within selected nodes)
    edge_tuples: list[tuple[str, str]] = []
    for edge in graph.edges.values():
        if edge.source_id in node_set and edge.target_id in node_set:
            pair = (min(edge.source_id, edge.target_id),
                    max(edge.source_id, edge.target_id))
            edge_tuples.append(pair)
    edge_tuples = sorted(set(edge_tuples))

    # Check cache
    cache_key = _layout_cache_key(node_ids, edge_tuples)
    cached = getattr(graph, "_layout_cache", None)
    if isinstance(cached, dict) and cached.get("key") == cache_key:
        return cached["result"]

    # Build adjacency
    adj = _build_adjacency(node_ids, edge_tuples)

    # Try numpy, fallback to pure Python
    try:
        import numpy  # noqa: F401
        result = _fr_numpy(adj, node_ids, iterations, width, height, seed, progress)
    except ImportError:
        result = _fr_pure(adj, node_ids, iterations, width, height, seed, progress)

    # Cache on graph object
    graph._layout_cache = {"key": cache_key, "result": result}  # type: ignore[attr-defined]

    return result
