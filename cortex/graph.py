"""
Cortex Graph Model — Phase 2 (v5.1)

Category-agnostic Node/Edge graph with backward-compatible v4 export.
Nodes are entities with tags (not category-scoped items).
Nodes carry temporal snapshots for history tracking.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Category ordering (used for v4 downgrade primary-tag selection)
# ---------------------------------------------------------------------------

CATEGORY_ORDER = [
    "identity", "professional_context", "business_context", "active_priorities",
    "work_history", "education_history",
    "relationships", "technical_expertise", "domain_knowledge", "market_context",
    "metrics", "constraints", "values", "negations", "user_preferences",
    "communication_preferences", "correction_history", "history", "mentions",
]


# ---------------------------------------------------------------------------
# Deterministic ID helpers
# ---------------------------------------------------------------------------

def _normalize_label(label: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return " ".join(label.lower().strip().split())


def diff_graphs(old: CortexGraph, new: CortexGraph) -> dict:
    """Diff two graphs. Returns added/removed/modified nodes and edges with a summary."""
    old_nids = set(old.nodes)
    new_nids = set(new.nodes)

    added_nodes = [
        {"id": nid, "label": new.nodes[nid].label, "tags": list(new.nodes[nid].tags)}
        for nid in sorted(new_nids - old_nids)
    ]
    removed_nodes = [
        {"id": nid, "label": old.nodes[nid].label, "tags": list(old.nodes[nid].tags)}
        for nid in sorted(old_nids - new_nids)
    ]

    modified_nodes: list[dict] = []
    for nid in sorted(old_nids & new_nids):
        a, b = old.nodes[nid], new.nodes[nid]
        changes: dict[str, dict] = {}
        if a.label != b.label:
            changes["label"] = {"old": a.label, "new": b.label}
        if a.confidence != b.confidence:
            changes["confidence"] = {"old": a.confidence, "new": b.confidence}
        if sorted(a.tags) != sorted(b.tags):
            changes["tags"] = {"old": sorted(a.tags), "new": sorted(b.tags)}
        if a.brief != b.brief:
            changes["brief"] = {"old": a.brief, "new": b.brief}
        if changes:
            modified_nodes.append({"id": nid, "label": b.label, "changes": changes})

    old_eids = set(old.edges)
    new_eids = set(new.edges)

    added_edges = [
        {"id": eid, "source": new.edges[eid].source_id,
         "target": new.edges[eid].target_id, "relation": new.edges[eid].relation}
        for eid in sorted(new_eids - old_eids)
    ]
    removed_edges = [
        {"id": eid, "source": old.edges[eid].source_id,
         "target": old.edges[eid].target_id, "relation": old.edges[eid].relation}
        for eid in sorted(old_eids - new_eids)
    ]

    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "modified_nodes": modified_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "summary": {
            "added": len(added_nodes),
            "removed": len(removed_nodes),
            "modified": len(modified_nodes),
            "edges_added": len(added_edges),
            "edges_removed": len(removed_edges),
        },
    }


def make_node_id(label: str) -> str:
    """Deterministic node ID: first 16 hex chars of SHA-256 of normalized label."""
    normalized = _normalize_label(label)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def make_node_id_with_tag(label: str, tag: str) -> str:
    """Collision-resistant node ID: append tag to the hash input."""
    normalized = _normalize_label(label)
    data = f"{normalized}:{tag}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def make_edge_id(source_id: str, target_id: str, relation: str) -> str:
    """Deterministic edge ID from (source, target, relation)."""
    data = f"{source_id}:{target_id}:{relation}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Node:
    id: str
    label: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    properties: dict = field(default_factory=dict)
    brief: str = ""
    full_description: str = ""
    mention_count: int = 1
    extraction_method: str = "mentioned"
    metrics: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    source_quotes: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    relationship_type: str = ""
    snapshots: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "tags": list(self.tags),
            "confidence": round(self.confidence, 2),
            "properties": dict(self.properties),
            "brief": self.brief,
            "full_description": self.full_description,
            "mention_count": self.mention_count,
            "extraction_method": self.extraction_method,
            "metrics": list(self.metrics),
            "timeline": list(self.timeline),
            "source_quotes": list(self.source_quotes),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "relationship_type": self.relationship_type,
            "snapshots": [{k: list(v) if isinstance(v, list) else v for k, v in s.items()} for s in self.snapshots],
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Node:
        return cls(
            id=d["id"],
            label=d["label"],
            tags=list(d.get("tags", [])),
            confidence=d.get("confidence", 0.5),
            properties=dict(d.get("properties", {})),
            brief=d.get("brief", ""),
            full_description=d.get("full_description", ""),
            mention_count=d.get("mention_count", 1),
            extraction_method=d.get("extraction_method", "mentioned"),
            metrics=list(d.get("metrics", [])),
            timeline=list(d.get("timeline", [])),
            source_quotes=list(d.get("source_quotes", [])),
            first_seen=d.get("first_seen", ""),
            last_seen=d.get("last_seen", ""),
            relationship_type=d.get("relationship_type", ""),
            snapshots=list(d.get("snapshots", [])),
        )


@dataclass
class Edge:
    id: str
    source_id: str
    target_id: str
    relation: str
    confidence: float = 0.5
    properties: dict = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "confidence": round(self.confidence, 2),
            "properties": dict(self.properties),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Edge:
        return cls(
            id=d["id"],
            source_id=d["source_id"],
            target_id=d["target_id"],
            relation=d["relation"],
            confidence=d.get("confidence", 0.5),
            properties=d.get("properties", {}),
            first_seen=d.get("first_seen", ""),
            last_seen=d.get("last_seen", ""),
        )


@dataclass
class CortexGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    schema_version: str = "5.0"
    meta: dict = field(default_factory=dict)
    _adjacency: dict[str, list[tuple[str, Edge]]] | None = field(
        default=None, repr=False, compare=False,
    )

    # ── Adjacency cache ──────────────────────────────────────────────────

    def _build_adjacency(self) -> dict[str, list[tuple[str, Edge]]]:
        """Build adjacency list: node_id -> [(neighbor_id, edge), ...]."""
        adj: dict[str, list[tuple[str, Edge]]] = {nid: [] for nid in self.nodes}
        for edge in self.edges.values():
            if edge.source_id in adj:
                adj[edge.source_id].append((edge.target_id, edge))
            if edge.target_id in adj:
                adj[edge.target_id].append((edge.source_id, edge))
        return adj

    def _get_adjacency(self) -> dict[str, list[tuple[str, Edge]]]:
        """Return cached adjacency list, building it lazily if needed."""
        if self._adjacency is None:
            self._adjacency = self._build_adjacency()
        return self._adjacency

    def _invalidate_adjacency(self) -> None:
        """Clear the cached adjacency list after graph mutations."""
        self._adjacency = None

    # ── CRUD ────────────────────────────────────────────────────────────

    def add_node(self, node: Node) -> str:
        self.nodes[node.id] = node
        self._invalidate_search_index()
        self._invalidate_adjacency()
        return node.id

    def add_edge(self, edge: Edge) -> str:
        self.edges[edge.id] = edge
        self._invalidate_adjacency()
        return edge.id

    def get_node(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Edge | None:
        return self.edges.get(edge_id)

    def remove_node(self, node_id: str) -> bool:
        if node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        # Remove connected edges
        to_remove = [
            eid for eid, e in self.edges.items()
            if e.source_id == node_id or e.target_id == node_id
        ]
        for eid in to_remove:
            del self.edges[eid]
        self._invalidate_search_index()
        self._invalidate_adjacency()
        return True

    def remove_edge(self, edge_id: str) -> bool:
        if edge_id not in self.edges:
            return False
        del self.edges[edge_id]
        self._invalidate_adjacency()
        return True

    # ── Temporal ─────────────────────────────────────────────────────────

    def create_snapshot(self, source: str, timestamp: str | None = None) -> None:
        """Append a snapshot dict to every node in the graph.

        Uses cortex.temporal.create_snapshot_dict for the actual snapshot
        creation, keeping graph.py lightweight.
        """
        from cortex.temporal import create_snapshot_dict
        for node in self.nodes.values():
            snap = create_snapshot_dict(node, source, timestamp)
            node.snapshots.append(snap)

    def graph_at(self, timestamp: str) -> CortexGraph:
        """Return a filtered copy of the graph reflecting state at *timestamp*.

        For each node, finds the latest snapshot at or before *timestamp*.
        If a node has no snapshots at or before the timestamp, it is included
        only if its first_seen is at or before the timestamp (or first_seen is empty).
        Snapshot state (confidence, tags) is applied to the returned copy.
        """
        result = CortexGraph(
            schema_version=self.schema_version,
            meta=dict(self.meta),
        )

        def _normalize_ts(ts: str) -> str:
            """Normalize Z suffix to +00:00 for consistent comparison."""
            if ts.endswith("Z"):
                return ts[:-1] + "+00:00"
            return ts

        norm_timestamp = _normalize_ts(timestamp)

        for nid, node in self.nodes.items():
            # Check if node existed at this time
            if node.first_seen and _normalize_ts(node.first_seen) > norm_timestamp:
                continue

            node_copy = copy.deepcopy(node)

            # Find latest snapshot at or before timestamp (skip empty timestamps)
            applicable = [
                s for s in node.snapshots
                if s.get("timestamp", "") and _normalize_ts(s.get("timestamp", "")) <= norm_timestamp
            ]
            if applicable:
                applicable.sort(key=lambda s: s.get("timestamp", ""))
                latest = applicable[-1]
                node_copy.confidence = latest.get("confidence", node.confidence)
                node_copy.tags = list(latest.get("tags", node.tags))

            # Only include snapshots up to the timestamp (skip empty timestamps)
            node_copy.snapshots = [
                s for s in node_copy.snapshots
                if s.get("timestamp", "") and _normalize_ts(s.get("timestamp", "")) <= norm_timestamp
            ]

            result.nodes[nid] = node_copy

        # Include edges where both endpoints exist in the result
        for eid, edge in self.edges.items():
            if edge.source_id in result.nodes and edge.target_id in result.nodes:
                result.edges[eid] = copy.deepcopy(edge)

        return result

    # ── Query ───────────────────────────────────────────────────────────

    def find_nodes(
        self,
        label: str | None = None,
        tag: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[Node]:
        results = []
        for node in self.nodes.values():
            if node.confidence < min_confidence:
                continue
            if label is not None and _normalize_label(node.label) != _normalize_label(label):
                continue
            if tag is not None and tag not in node.tags:
                continue
            results.append(node)
        return results

    def get_neighbors(
        self, node_id: str, relation: str | None = None
    ) -> list[tuple[Edge, Node]]:
        adj = self._get_adjacency()
        results = []
        for neighbor_id, edge in adj.get(node_id, []):
            if relation is not None and edge.relation != relation:
                continue
            neighbor = self.nodes.get(neighbor_id)
            if neighbor:
                results.append((edge, neighbor))
        return results

    def get_edges_for(self, node_id: str) -> list[Edge]:
        adj = self._get_adjacency()
        return [edge for _, edge in adj.get(node_id, [])]

    # ── Update ─────────────────────────────────────────────────────────

    def update_node(self, node_id: str, updates: dict) -> Node | None:
        """Partial update of node fields. Returns updated node or None if not found."""
        node = self.nodes.get(node_id)
        if node is None:
            return None
        allowed = {
            "label", "tags", "confidence", "properties", "brief",
            "full_description", "mention_count", "extraction_method",
            "metrics", "timeline", "source_quotes", "relationship_type",
        }
        for key, value in updates.items():
            if key in allowed and hasattr(node, key):
                setattr(node, key, value)
        node.last_seen = datetime.now(timezone.utc).isoformat()
        self._invalidate_search_index()
        return node

    # ── Search ─────────────────────────────────────────────────────────

    def search_nodes(
        self,
        query: str,
        fields: list[str] | None = None,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> list[Node]:
        """Full-text substring search across node fields.

        Searches label, brief, full_description, and property values
        by default. Case-insensitive.
        """
        if not query:
            return []
        q_lower = query.lower()
        default_fields = {"label", "brief", "full_description", "properties"}
        search_fields = set(fields) if fields else default_fields
        results = []
        for node in self.nodes.values():
            if node.confidence < min_confidence:
                continue
            matched = False
            if "label" in search_fields and q_lower in node.label.lower():
                matched = True
            if not matched and "brief" in search_fields and q_lower in node.brief.lower():
                matched = True
            if not matched and "full_description" in search_fields and q_lower in node.full_description.lower():
                matched = True
            if not matched and "properties" in search_fields:
                for v in node.properties.values():
                    if isinstance(v, str) and q_lower in v.lower():
                        matched = True
                        break
            if matched:
                results.append(node)
                if len(results) >= limit:
                    break
        return results

    def semantic_search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict]:
        """TF-IDF relevance-ranked search across node text fields.

        Returns list of ``{"node": <Node>, "score": <float>}`` sorted by
        descending relevance.  The index is built lazily on first call and
        cached until a mutation invalidates it.
        """
        from cortex.search import TFIDFIndex

        if not hasattr(self, "_search_index") or not self._search_index.is_built:
            self._search_index = TFIDFIndex()
            self._search_index.build(self.nodes.values())
        results = self._search_index.search(query, limit=limit, min_score=min_score)
        # Replace node dicts with actual Node objects where available
        for r in results:
            node_id = r["node"].get("id", "")
            if node_id in self.nodes:
                r["node"] = self.nodes[node_id]
        return results

    def _invalidate_search_index(self) -> None:
        """Clear the cached search index after graph mutations."""
        if hasattr(self, "_search_index"):
            self._search_index.clear()

    # ── Graph traversal ────────────────────────────────────────────────

    def shortest_path(
        self, source_id: str, target_id: str, max_depth: int = 10
    ) -> list[str]:
        """BFS shortest path from source to target. Returns list of node IDs (empty if unreachable)."""
        if source_id not in self.nodes or target_id not in self.nodes:
            return []
        if source_id == target_id:
            return [source_id]

        adj = self._get_adjacency()

        from collections import deque
        visited: set[str] = {source_id}
        queue: deque[tuple[str, list[str]]] = deque([(source_id, [source_id])])

        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                break
            for neighbor_id, _ in adj.get(current, []):
                if neighbor_id == target_id:
                    return path + [neighbor_id]
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, path + [neighbor_id]))
        return []

    def k_hop_neighborhood(
        self, node_id: str, k: int = 2
    ) -> tuple[set[str], set[str]]:
        """Return (node_ids, edge_ids) within k hops of node_id."""
        if node_id not in self.nodes:
            return set(), set()

        adj = self._get_adjacency()
        visited_nodes: set[str] = {node_id}
        frontier: set[str] = {node_id}
        visited_edges: set[str] = set()

        for _ in range(k):
            next_frontier: set[str] = set()
            for nid in frontier:
                for neighbor_id, edge in adj.get(nid, []):
                    if neighbor_id not in visited_nodes:
                        visited_nodes.add(neighbor_id)
                        next_frontier.add(neighbor_id)
                        visited_edges.add(edge.id)
                    elif neighbor_id in visited_nodes:
                        visited_edges.add(edge.id)
            frontier = next_frontier

        return visited_nodes, visited_edges

    # ── Merge ───────────────────────────────────────────────────────────

    def merge_nodes(self, node_id_a: str, node_id_b: str) -> Node:
        """Merge node B into node A. Re-wire edges. Remove B."""
        a = self.nodes[node_id_a]
        b = self.nodes[node_id_b]

        # Merge fields
        a.confidence = max(a.confidence, b.confidence)
        a.mention_count += b.mention_count
        a.tags = list(dict.fromkeys(a.tags + b.tags))  # deduplicated, order preserved
        if len(b.brief) > len(a.brief):
            a.brief = b.brief
        if len(b.full_description) > len(a.full_description):
            a.full_description = b.full_description
        a.metrics = list(dict.fromkeys(a.metrics + b.metrics))
        a.timeline = list(dict.fromkeys(a.timeline + b.timeline))
        a.source_quotes = list(dict.fromkeys(a.source_quotes + b.source_quotes))[:5]
        if b.first_seen and (not a.first_seen or b.first_seen < a.first_seen):
            a.first_seen = b.first_seen
        if b.last_seen and (not a.last_seen or b.last_seen > a.last_seen):
            a.last_seen = b.last_seen
        # Merge properties
        for k, v in b.properties.items():
            if k not in a.properties:
                a.properties[k] = v

        # Re-wire edges from B to A
        edges_to_remove = []
        edges_to_add = []
        for eid, edge in self.edges.items():
            if edge.source_id == node_id_b or edge.target_id == node_id_b:
                edges_to_remove.append(eid)
                new_src = node_id_a if edge.source_id == node_id_b else edge.source_id
                new_tgt = node_id_a if edge.target_id == node_id_b else edge.target_id
                # Skip self-loops
                if new_src == new_tgt:
                    continue
                new_eid = make_edge_id(new_src, new_tgt, edge.relation)
                # Skip if an equivalent edge already exists
                if new_eid in self.edges:
                    continue
                new_edge = Edge(
                    id=new_eid,
                    source_id=new_src,
                    target_id=new_tgt,
                    relation=edge.relation,
                    confidence=edge.confidence,
                    properties=dict(edge.properties),
                    first_seen=edge.first_seen,
                    last_seen=edge.last_seen,
                )
                edges_to_add.append(new_edge)

        for eid in edges_to_remove:
            self.edges.pop(eid, None)
        for e in edges_to_add:
            self.edges[e.id] = e

        # Remove node B
        del self.nodes[node_id_b]
        self._invalidate_adjacency()
        return a

    # ── Centrality ────────────────────────────────────────────────────

    def compute_centrality(self) -> dict[str, float]:
        """Compute centrality scores for all nodes."""
        from cortex.centrality import compute_centrality
        return compute_centrality(self)

    def apply_centrality_boost(self) -> dict[str, float]:
        """Compute centrality and boost top-decile node confidence."""
        from cortex.centrality import apply_centrality_boost, compute_centrality
        scores = compute_centrality(self)
        apply_centrality_boost(self, scores)
        return scores

    # ── Export ──────────────────────────────────────────────────────────

    def to_v4_categories(self) -> dict:
        """Compute v4-compatible flat category dict from the graph."""
        categories: dict[str, list[dict]] = {}
        for node in self.nodes.values():
            primary_tag = self._primary_tag(node)
            topic_dict = {
                "topic": node.label,
                "brief": node.brief or node.label,
                "full_description": node.full_description,
                "confidence": round(node.confidence, 2),
                "mention_count": node.mention_count,
                "extraction_method": node.extraction_method,
                "metrics": node.metrics[:10],
                "relationships": self._node_relationship_labels(node.id),
                "timeline": node.timeline[:5],
                "source_quotes": node.source_quotes[:3],
                "first_seen": node.first_seen or None,
                "last_seen": node.last_seen or None,
                "_node_id": node.id,
            }
            if node.relationship_type:
                topic_dict["relationship_type"] = node.relationship_type
            categories.setdefault(primary_tag, []).append(topic_dict)

        # Sort each category by (confidence, mention_count) descending
        for cat in categories:
            categories[cat].sort(
                key=lambda t: (t["confidence"], t["mention_count"]), reverse=True
            )
        return categories

    def _primary_tag(self, node: Node) -> str:
        """First tag in CATEGORY_ORDER, or first tag, or 'mentions'."""
        for cat in CATEGORY_ORDER:
            if cat in node.tags:
                return cat
        return node.tags[0] if node.tags else "mentions"

    def _node_relationship_labels(self, node_id: str) -> list[str]:
        """Get labels of nodes connected to this node (for v4 compat)."""
        adj = self._get_adjacency()
        labels = []
        for neighbor_id, _ in adj.get(node_id, []):
            neighbor = self.nodes.get(neighbor_id)
            if neighbor:
                labels.append(neighbor.label)
        return labels[:10]

    def to_v5_json(self) -> dict:
        """Full v5 schema JSON dict."""
        return {
            "schema_version": self.schema_version,
            "meta": {
                **self.meta,
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
            },
            "graph": {
                "nodes": {
                    nid: node.to_dict() for nid, node in self.nodes.items()
                },
                "edges": {
                    eid: edge.to_dict() for eid, edge in self.edges.items()
                },
            },
            "categories": self.to_v4_categories(),
        }

    def export_v4(self) -> dict:
        """Complete v4-compatible JSON (no graph block)."""
        return {
            "schema_version": "4.0",
            "meta": {
                **self.meta,
                "generated_at": self.meta.get(
                    "generated_at",
                    datetime.now(timezone.utc).isoformat(),
                ),
                "method": "aggressive_extraction_v4",
                "features": [
                    "semantic_dedup", "time_decay", "topic_merging",
                    "conflict_detection", "typed_relationships",
                ],
            },
            "categories": self.to_v4_categories(),
        }

    def export_v5(self) -> dict:
        """Complete v5 JSON with graph + backward-compat categories."""
        generated_at = self.meta.get(
            "generated_at",
            datetime.now(timezone.utc).isoformat(),
        )
        return {
            "schema_version": "6.0",
            "meta": {
                **self.meta,
                "generated_at": generated_at,
                "method": "aggressive_extraction_v5",
                "features": [
                    "graph_model", "multi_tag_nodes", "semantic_dedup",
                    "time_decay", "typed_relationships",
                    "smart_edges", "centrality",
                    "query_engine", "intelligence",
                    "visualization", "dashboard",
                ],
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
            },
            "graph": {
                "nodes": {
                    nid: node.to_dict() for nid, node in self.nodes.items()
                },
                "edges": {
                    eid: edge.to_dict() for eid, edge in self.edges.items()
                },
            },
            "categories": self.to_v4_categories(),
        }

    # ── Health ─────────────────────────────────────────────────────────

    def graph_health(self, stale_days: int = 30) -> dict:
        """Compute graph health metrics: stale nodes, orphans, confidence distribution."""
        now = datetime.now(timezone.utc)

        # Build set of node IDs referenced by any edge
        referenced: set[str] = set()
        for edge in self.edges.values():
            referenced.add(edge.source_id)
            referenced.add(edge.target_id)

        stale_nodes: list[dict] = []
        orphan_nodes: list[dict] = []
        confidences: list[float] = []
        tag_conf_sums: dict[str, float] = {}
        tag_conf_counts: dict[str, int] = {}

        for nid, node in self.nodes.items():
            confidences.append(node.confidence)
            for tag in node.tags:
                tag_conf_sums[tag] = tag_conf_sums.get(tag, 0.0) + node.confidence
                tag_conf_counts[tag] = tag_conf_counts.get(tag, 0) + 1

            # Stale check
            date_str = node.last_seen or node.first_seen
            if date_str:
                try:
                    ts = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    days = (now - ts).days
                    if days > stale_days:
                        stale_nodes.append({
                            "id": nid,
                            "label": node.label,
                            "last_seen": date_str,
                            "days_stale": days,
                        })
                except (ValueError, TypeError):
                    pass

            # Orphan check
            if nid not in referenced:
                orphan_nodes.append({
                    "id": nid,
                    "label": node.label,
                    "tags": list(node.tags),
                })

        # Confidence distribution buckets
        buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        for c in confidences:
            if c < 0.2:
                buckets["0.0-0.2"] += 1
            elif c < 0.4:
                buckets["0.2-0.4"] += 1
            elif c < 0.6:
                buckets["0.4-0.6"] += 1
            elif c < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1

        avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        avg_per_tag = {
            tag: round(tag_conf_sums[tag] / tag_conf_counts[tag], 4)
            for tag in sorted(tag_conf_sums)
        }

        return {
            "stale_nodes": stale_nodes,
            "stale_count": len(stale_nodes),
            "orphan_nodes": orphan_nodes,
            "orphan_count": len(orphan_nodes),
            "confidence_distribution": buckets,
            "avg_confidence": avg_confidence,
            "avg_confidence_per_tag": avg_per_tag,
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
        }

    # ── Stats ──────────────────────────────────────────────────────────

    def stats(self) -> dict:
        tag_dist: dict[str, int] = {}
        for node in self.nodes.values():
            for tag in node.tags:
                tag_dist[tag] = tag_dist.get(tag, 0) + 1

        degree_map: dict[str, int] = {nid: 0 for nid in self.nodes}
        rel_dist: dict[str, int] = {}
        for e in self.edges.values():
            if e.source_id in degree_map:
                degree_map[e.source_id] += 1
            if e.target_id in degree_map:
                degree_map[e.target_id] += 1
            rel_dist[e.relation] = rel_dist.get(e.relation, 0) + 1

        degrees = list(degree_map.values())
        avg_degree = sum(degrees) / len(degrees) if degrees else 0.0
        isolated = sum(1 for d in degrees if d == 0)

        # Top-5 by degree
        top_central = sorted(
            degree_map.items(), key=lambda x: x[1], reverse=True,
        )[:5]
        top_labels = [
            self.nodes[nid].label for nid, _ in top_central
            if nid in self.nodes
        ]

        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "avg_degree": round(avg_degree, 2),
            "tag_distribution": tag_dist,
            "relation_distribution": rel_dist,
            "isolated_nodes": isolated,
            "top_central_nodes": top_labels,
        }

    # ── Deserialization ────────────────────────────────────────────────

    @classmethod
    def from_v5_json(cls, data: dict) -> CortexGraph:
        """Load a CortexGraph from a v5 JSON dict."""
        graph = cls(
            schema_version=data.get("schema_version", "5.0"),
            meta=data.get("meta", {}),
        )
        graph_data = data.get("graph", {})
        for nid, nd in graph_data.get("nodes", {}).items():
            graph.nodes[nid] = Node.from_dict(nd)
        for eid, ed in graph_data.get("edges", {}).items():
            graph.edges[eid] = Edge.from_dict(ed)
        return graph
