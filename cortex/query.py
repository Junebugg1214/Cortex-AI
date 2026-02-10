"""
Cortex Query Engine + Graph Algorithms — Phase 5 (v5.4)

Structured query interface for CortexGraph traversal.
Graph algorithms: shortest_path (BFS), connected_components (union-find),
betweenness_centrality (Brandes algorithm, only for >= 50 nodes).
Pure Python stdlib — no external dependencies.
"""

from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING

from cortex.graph import Node, _normalize_label

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


# ---------------------------------------------------------------------------
# Graph Algorithms
# ---------------------------------------------------------------------------

def _build_adjacency(graph: CortexGraph) -> dict[str, set[str]]:
    """Build undirected adjacency list from graph edges."""
    adj: dict[str, set[str]] = {nid: set() for nid in graph.nodes}
    for edge in graph.edges.values():
        if edge.source_id in adj and edge.target_id in adj:
            adj[edge.source_id].add(edge.target_id)
            adj[edge.target_id].add(edge.source_id)
    return adj


def shortest_path(graph: CortexGraph, from_id: str, to_id: str) -> list[str]:
    """BFS shortest path between two nodes. Returns node ID list, or [] if no path."""
    if from_id not in graph.nodes or to_id not in graph.nodes:
        return []
    if from_id == to_id:
        return [from_id]

    adj = _build_adjacency(graph)
    visited: set[str] = {from_id}
    queue: deque[list[str]] = deque([[from_id]])

    while queue:
        path = queue.popleft()
        current = path[-1]
        for neighbor in adj.get(current, set()):
            if neighbor == to_id:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])

    return []


def connected_components(graph: CortexGraph) -> list[set[str]]:
    """Union-find connected components. Returns list of sets, sorted by size desc."""
    if not graph.nodes:
        return []

    parent: dict[str, str] = {nid: nid for nid in graph.nodes}
    rank: dict[str, int] = {nid: 0 for nid in graph.nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    for edge in graph.edges.values():
        if edge.source_id in parent and edge.target_id in parent:
            union(edge.source_id, edge.target_id)

    groups: dict[str, set[str]] = {}
    for nid in graph.nodes:
        root = find(nid)
        groups.setdefault(root, set()).add(nid)

    return sorted(groups.values(), key=len, reverse=True)


def betweenness_centrality(graph: CortexGraph) -> dict[str, float]:
    """Brandes algorithm for betweenness centrality (undirected).

    Only activates for graphs with >= 50 nodes.
    Returns normalized scores: divided by (n-1)*(n-2)/2.
    """
    n = len(graph.nodes)
    if n < 50:
        return {}

    adj = _build_adjacency(graph)
    nodes = list(graph.nodes.keys())
    cb: dict[str, float] = {nid: 0.0 for nid in nodes}

    for s in nodes:
        # BFS from s
        stack: list[str] = []
        pred: dict[str, list[str]] = {nid: [] for nid in nodes}
        sigma: dict[str, int] = {nid: 0 for nid in nodes}
        sigma[s] = 1
        dist: dict[str, int] = {nid: -1 for nid in nodes}
        dist[s] = 0
        queue: deque[str] = deque([s])

        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adj.get(v, set()):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        # Back-propagation
        delta: dict[str, float] = {nid: 0.0 for nid in nodes}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]

    # Normalize for undirected graph: Brandes double-counts pairs
    denom = (n - 1) * (n - 2)
    if denom > 0:
        for nid in cb:
            cb[nid] /= denom

    return cb


# ---------------------------------------------------------------------------
# QueryEngine
# ---------------------------------------------------------------------------

class QueryEngine:
    """Structured query interface for CortexGraph."""

    def __init__(self, graph: CortexGraph) -> None:
        self.graph = graph

    def query_category(self, tag: str) -> list[Node]:
        """Return nodes with the given tag, sorted by confidence desc."""
        nodes = self.graph.find_nodes(tag=tag)
        nodes.sort(key=lambda n: n.confidence, reverse=True)
        return nodes

    def query_path(self, from_label: str, to_label: str) -> list[list[Node]]:
        """Find shortest path between two labels. Returns list with one path, or []."""
        src_nodes = self.graph.find_nodes(label=from_label)
        tgt_nodes = self.graph.find_nodes(label=to_label)
        if not src_nodes or not tgt_nodes:
            return []

        path_ids = shortest_path(self.graph, src_nodes[0].id, tgt_nodes[0].id)
        if not path_ids:
            return []

        path_nodes = []
        for nid in path_ids:
            node = self.graph.get_node(nid)
            if node:
                path_nodes.append(node)
        return [path_nodes] if path_nodes else []

    def query_changed(self, since: str) -> dict:
        """Return nodes that changed since the given ISO-8601 date string."""
        new_nodes: list[dict] = []
        updated_nodes: list[dict] = []

        def _norm_ts(t: str) -> str:
            return t[:-1] + "+00:00" if t.endswith("Z") else t

        norm_since = _norm_ts(since)

        for node in self.graph.nodes.values():
            node_info = {
                "id": node.id,
                "label": node.label,
                "tags": list(node.tags),
                "confidence": node.confidence,
            }

            # New node: first_seen >= since
            if node.first_seen and _norm_ts(node.first_seen) >= norm_since:
                new_nodes.append(node_info)
                continue

            # Updated: any snapshot timestamp >= since
            has_update = False
            for snap in node.snapshots:
                ts = snap.get("timestamp", "")
                if ts and _norm_ts(ts) >= norm_since:
                    has_update = True
                    break
            # Or last_seen >= since (and not new)
            if not has_update and node.last_seen and _norm_ts(node.last_seen) >= norm_since:
                has_update = True

            if has_update:
                updated_nodes.append(node_info)

        return {
            "since": since,
            "new_nodes": new_nodes,
            "updated_nodes": updated_nodes,
            "total_changed": len(new_nodes) + len(updated_nodes),
        }

    def query_related(self, label: str, depth: int = 2) -> list[Node]:
        """BFS traversal to `depth` hops from the labeled node. Excludes seed."""
        seed_nodes = self.graph.find_nodes(label=label)
        if not seed_nodes:
            return []

        seed_id = seed_nodes[0].id
        adj = _build_adjacency(self.graph)
        visited: set[str] = {seed_id}
        current_layer: set[str] = {seed_id}
        result_ids: list[str] = []

        for _ in range(depth):
            next_layer: set[str] = set()
            for nid in current_layer:
                for neighbor in adj.get(nid, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_layer.add(neighbor)
                        result_ids.append(neighbor)
            current_layer = next_layer

        result = [self.graph.get_node(nid) for nid in result_ids if self.graph.get_node(nid)]
        result.sort(key=lambda n: n.confidence, reverse=True)
        return result

    def query_strongest(self, n: int = 10) -> list[Node]:
        """Top N nodes by confidence (desc), then mention_count (desc)."""
        nodes = list(self.graph.nodes.values())
        nodes.sort(key=lambda nd: (nd.confidence, nd.mention_count), reverse=True)
        return nodes[:n]

    def query_weakest(self, n: int = 10) -> list[Node]:
        """Bottom N nodes by confidence (asc), then mention_count (asc)."""
        nodes = list(self.graph.nodes.values())
        nodes.sort(key=lambda nd: (nd.confidence, nd.mention_count))
        return nodes[:n]


# ---------------------------------------------------------------------------
# NL Syntactic Sugar
# ---------------------------------------------------------------------------

_NL_CATEGORY = re.compile(r"what\s+are\s+my\s+(\w[\w_]*)", re.IGNORECASE)
_NL_PATH = re.compile(r"how\s+does\s+(.+?)\s+relate\s+to\s+(.+)", re.IGNORECASE)
_NL_CHANGED = re.compile(r"what\s+changed\s+since\s+(.+)", re.IGNORECASE)


def parse_nl_query(query_str: str, engine: QueryEngine) -> dict | list | str:
    """Pattern-match limited NL queries to structured methods.

    Returns result data or error string for unrecognized queries.
    """
    m = _NL_CATEGORY.match(query_str.strip())
    if m:
        tag = m.group(1)
        nodes = engine.query_category(tag)
        return [{"label": n.label, "confidence": n.confidence, "tags": n.tags} for n in nodes]

    m = _NL_PATH.match(query_str.strip())
    if m:
        from_label = m.group(1).strip()
        to_label = m.group(2).strip()
        paths = engine.query_path(from_label, to_label)
        if not paths:
            return {"path": [], "found": False}
        return {
            "path": [{"label": n.label, "tags": n.tags} for n in paths[0]],
            "found": True,
        }

    m = _NL_CHANGED.match(query_str.strip())
    if m:
        since = m.group(1).strip()
        return engine.query_changed(since)

    return (
        "Query not recognized. Supported: "
        "'what are my <tag>', "
        "'how does X relate to Y', "
        "'what changed since <date>'."
    )
