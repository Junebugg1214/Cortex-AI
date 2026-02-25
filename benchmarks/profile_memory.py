#!/usr/bin/env python3
"""
Memory profiling for Cortex graph operations.

Uses stdlib tracemalloc to measure peak memory usage during common
graph operations: build, adjacency, traversal, export, search.

Usage::

    python3 benchmarks/profile_memory.py
    python3 benchmarks/profile_memory.py --nodes 5000 --edges 10000
"""

from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
import uuid

# Add project root to path
sys.path.insert(0, ".")

from cortex.graph import CortexGraph, Edge, Node, make_edge_id, make_node_id


def _build_graph(n_nodes: int, n_edges: int) -> CortexGraph:
    """Build a random graph with n_nodes and n_edges."""
    import random

    graph = CortexGraph()
    node_ids = []

    for i in range(n_nodes):
        label = f"node-{i}-{uuid.uuid4().hex[:6]}"
        nid = make_node_id(label)
        node = Node(
            id=nid,
            label=label,
            tags=["benchmark", f"group-{i % 10}"],
            confidence=random.uniform(0.3, 1.0),
            brief=f"Benchmark node {i}",
        )
        graph.add_node(node)
        node_ids.append(nid)

    for _ in range(n_edges):
        src = random.choice(node_ids)
        tgt = random.choice(node_ids)
        if src == tgt:
            continue
        relation = random.choice(["related_to", "depends_on", "uses", "part_of"])
        eid = make_edge_id(src, tgt, relation)
        edge = Edge(id=eid, source_id=src, target_id=tgt, relation=relation)
        graph.add_edge(edge)

    return graph


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    else:
        return f"{n / (1024 * 1024):.1f} MiB"


def profile_operation(name: str, fn, *args, **kwargs):
    """Run fn, measure time and peak memory delta."""
    tracemalloc.start()
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  {name:40s}  {elapsed*1000:8.1f} ms  peak={_fmt_bytes(peak)}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Profile Cortex graph memory usage")
    parser.add_argument("--nodes", type=int, default=1000, help="Number of nodes")
    parser.add_argument("--edges", type=int, default=3000, help="Number of edges")
    args = parser.parse_args()

    print(f"Building graph: {args.nodes} nodes, {args.edges} edges\n")

    graph = profile_operation("Graph construction", _build_graph, args.nodes, args.edges)

    print(f"\nGraph built: {len(graph.nodes)} nodes, {len(graph.edges)} edges\n")

    # Adjacency list build
    profile_operation("Adjacency list build", graph._build_adjacency)

    # Get neighbors (first node)
    first_nid = next(iter(graph.nodes))
    profile_operation("get_neighbors (single)", graph.get_neighbors, first_nid)

    # k-hop neighborhood
    profile_operation("k_hop_neighborhood (k=2)", graph.k_hop_neighborhood, first_nid, 2)

    # Shortest path (first -> last)
    last_nid = list(graph.nodes.keys())[-1]
    profile_operation("shortest_path", graph.shortest_path, first_nid, last_nid)

    # Full export
    profile_operation("export_v5 (full JSON)", graph.export_v5)

    # Stats
    profile_operation("stats()", graph.stats)

    # Search
    profile_operation("search_nodes('benchmark')", graph.search_nodes, "benchmark", limit=50)

    # Semantic search (builds TF-IDF index)
    profile_operation("semantic_search('benchmark')", graph.semantic_search, "benchmark", limit=10)

    print("\nDone.")


if __name__ == "__main__":
    main()
