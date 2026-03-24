"""
Cortex Intelligence Layer — Phase 5 (v5.4)

Gap analysis and weekly digest generation for CortexGraph.
Pure Python stdlib — no external dependencies.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from cortex.graph import CATEGORY_ORDER, Node, _normalize_label

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


def _normalize_timestamp(timestamp: str) -> str:
    if not timestamp:
        return ""
    value = timestamp.strip()
    if not value:
        return ""
    try:
        normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    else:
        normalized = normalized.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _normalize_temporal_status(node: Node) -> str:
    raw = (getattr(node, "status", "") or "").strip().lower()
    if raw in {"planned", "future", "upcoming", "intended"}:
        return "planned"
    if raw in {"active", "current", "ongoing", "present"}:
        return "active"
    if raw in {"historical", "past", "former", "inactive", "completed", "ended"}:
        return "historical"

    timeline = {str(item).strip().lower() for item in getattr(node, "timeline", [])}
    if "planned" in timeline or "future" in timeline:
        return "planned"
    if "past" in timeline or "historical" in timeline:
        return "historical"
    if "current" in timeline or "active" in timeline:
        return "active"
    return raw


# ---------------------------------------------------------------------------
# Gap Analyzer
# ---------------------------------------------------------------------------


class GapAnalyzer:
    """Detect gaps and blind spots in the knowledge graph."""

    def category_gaps(self, graph: CortexGraph) -> list[dict]:
        """Categories from CATEGORY_ORDER with zero nodes."""
        present_tags: set[str] = set()
        for node in graph.nodes.values():
            present_tags.update(node.tags)

        return [{"category": cat, "status": "empty"} for cat in CATEGORY_ORDER if cat not in present_tags]

    def confidence_gaps(
        self,
        graph: CortexGraph,
        threshold: float = 0.6,
    ) -> list[dict]:
        """Active priority nodes with confidence below threshold."""
        results: list[dict] = []
        for node in graph.nodes.values():
            if "active_priorities" in node.tags and node.confidence < threshold:
                results.append(
                    {
                        "node_id": node.id,
                        "label": node.label,
                        "confidence": node.confidence,
                        "tags": list(node.tags),
                    }
                )
        results.sort(key=lambda x: x["confidence"])
        return results

    def relationship_gaps(self, graph: CortexGraph) -> list[dict]:
        """Tag groups with >= 3 nodes but zero inter-group edges."""
        # Build tag → node IDs index
        tag_nodes: dict[str, set[str]] = {}
        for node in graph.nodes.values():
            for tag in node.tags:
                tag_nodes.setdefault(tag, set()).add(node.id)

        results: list[dict] = []
        for tag, nids in tag_nodes.items():
            if len(nids) < 3:
                continue
            # Count edges where both endpoints have this tag
            edge_count = 0
            for edge in graph.edges.values():
                if edge.source_id in nids and edge.target_id in nids:
                    edge_count += 1
            if edge_count == 0:
                results.append(
                    {
                        "tag": tag,
                        "node_count": len(nids),
                        "edge_count": 0,
                        "gap": "no relationships between nodes",
                    }
                )
        return results

    def isolated_nodes(self, graph: CortexGraph) -> list[Node]:
        """Nodes with zero edges, sorted by confidence desc."""
        connected: set[str] = set()
        for edge in graph.edges.values():
            connected.add(edge.source_id)
            connected.add(edge.target_id)

        isolated = [node for node in graph.nodes.values() if node.id not in connected]
        isolated.sort(key=lambda n: n.confidence, reverse=True)
        return isolated

    def stale_nodes(self, graph: CortexGraph, days: int = 180) -> list[Node]:
        """Nodes with last_seen older than cutoff, sorted by last_seen asc."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        stale: list[Node] = []

        for node in graph.nodes.values():
            timestamps = [node.last_seen] if node.last_seen else []
            timestamps.extend(snap.get("timestamp", "") for snap in node.snapshots if snap.get("timestamp"))
            if timestamps and max(timestamps) < cutoff:
                stale.append(node)

        stale.sort(
            key=lambda n: max(
                [n.last_seen] + [snap.get("timestamp", "") for snap in n.snapshots if snap.get("timestamp")]
            )
        )
        return stale

    def temporal_gaps(self, graph: CortexGraph, now: datetime | None = None) -> list[dict]:
        """Lifecycle and validity-window issues that make temporal claims ambiguous."""
        now = now or datetime.now(timezone.utc)
        now_iso = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        results: list[dict] = []

        for node in graph.nodes.values():
            status = _normalize_temporal_status(node)
            valid_from = _normalize_timestamp(getattr(node, "valid_from", "") or "")
            valid_to = _normalize_timestamp(getattr(node, "valid_to", "") or "")

            if valid_from and valid_to and valid_to < valid_from:
                results.append(
                    {
                        "node_id": node.id,
                        "label": node.label,
                        "kind": "invalid_window",
                        "status": status,
                        "valid_from": valid_from,
                        "valid_to": valid_to,
                    }
                )
            if status == "planned" and not valid_from:
                results.append(
                    {
                        "node_id": node.id,
                        "label": node.label,
                        "kind": "planned_missing_start",
                        "status": status,
                        "valid_from": valid_from,
                        "valid_to": valid_to,
                    }
                )
            if status == "historical" and not valid_to:
                results.append(
                    {
                        "node_id": node.id,
                        "label": node.label,
                        "kind": "historical_missing_end",
                        "status": status,
                        "valid_from": valid_from,
                        "valid_to": valid_to,
                    }
                )
            if status == "active" and valid_to and valid_to < now_iso:
                results.append(
                    {
                        "node_id": node.id,
                        "label": node.label,
                        "kind": "expired_still_active",
                        "status": status,
                        "valid_from": valid_from,
                        "valid_to": valid_to,
                    }
                )

        return results

    def all_gaps(self, graph: CortexGraph) -> dict:
        """Run all gap analyses and return combined dict."""
        isolated = self.isolated_nodes(graph)
        stale = self.stale_nodes(graph)
        return {
            "category_gaps": self.category_gaps(graph),
            "confidence_gaps": self.confidence_gaps(graph),
            "relationship_gaps": self.relationship_gaps(graph),
            "temporal_gaps": self.temporal_gaps(graph),
            "isolated_nodes": [{"id": n.id, "label": n.label, "confidence": n.confidence} for n in isolated],
            "stale_nodes": [{"id": n.id, "label": n.label, "last_seen": n.last_seen} for n in stale],
        }


# ---------------------------------------------------------------------------
# Insight Generator
# ---------------------------------------------------------------------------


class InsightGenerator:
    """Generate weekly digest by comparing two graph snapshots."""

    def digest(self, current: CortexGraph, previous: CortexGraph) -> dict:
        """Compare current vs previous graph. Returns diff dict."""
        # Build label → node list maps (handle multiple nodes with same label)
        from collections import defaultdict as _defaultdict

        from cortex.contradictions import ContradictionEngine
        from cortex.temporal import drift_score

        _cur_multi: dict[str, list[Node]] = _defaultdict(list)
        for node in current.nodes.values():
            _cur_multi[_normalize_label(node.label)].append(node)
        # Pick highest-confidence node per label for comparison
        cur_by_label: dict[str, Node] = {
            label: max(nodes, key=lambda n: n.confidence) for label, nodes in _cur_multi.items()
        }

        _prev_multi: dict[str, list[Node]] = _defaultdict(list)
        for node in previous.nodes.values():
            _prev_multi[_normalize_label(node.label)].append(node)
        prev_by_label: dict[str, Node] = {
            label: max(nodes, key=lambda n: n.confidence) for label, nodes in _prev_multi.items()
        }

        cur_labels = set(cur_by_label.keys())
        prev_labels = set(prev_by_label.keys())

        # New nodes
        new_nodes = [
            {
                "label": cur_by_label[lbl].label,
                "tags": list(cur_by_label[lbl].tags),
                "confidence": cur_by_label[lbl].confidence,
            }
            for lbl in sorted(cur_labels - prev_labels)
        ]

        # Removed nodes
        removed_nodes = [
            {
                "label": prev_by_label[lbl].label,
                "tags": list(prev_by_label[lbl].tags),
                "confidence": prev_by_label[lbl].confidence,
            }
            for lbl in sorted(prev_labels - cur_labels)
        ]

        # Confidence changes > 0.2
        confidence_changes: list[dict] = []
        for lbl in cur_labels & prev_labels:
            cur_conf = cur_by_label[lbl].confidence
            prev_conf = prev_by_label[lbl].confidence
            delta = cur_conf - prev_conf
            if abs(delta) > 0.2:
                confidence_changes.append(
                    {
                        "label": cur_by_label[lbl].label,
                        "previous": prev_conf,
                        "current": cur_conf,
                        "delta": round(delta, 4),
                    }
                )
        confidence_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)

        temporal_changes: list[dict] = []
        for lbl in cur_labels & prev_labels:
            cur_node = cur_by_label[lbl]
            prev_node = prev_by_label[lbl]
            cur_status = _normalize_temporal_status(cur_node)
            prev_status = _normalize_temporal_status(prev_node)
            cur_valid_from = _normalize_timestamp(getattr(cur_node, "valid_from", "") or "")
            prev_valid_from = _normalize_timestamp(getattr(prev_node, "valid_from", "") or "")
            cur_valid_to = _normalize_timestamp(getattr(cur_node, "valid_to", "") or "")
            prev_valid_to = _normalize_timestamp(getattr(prev_node, "valid_to", "") or "")

            if cur_status == prev_status and cur_valid_from == prev_valid_from and cur_valid_to == prev_valid_to:
                continue

            temporal_changes.append(
                {
                    "label": cur_node.label,
                    "previous_status": prev_status,
                    "current_status": cur_status,
                    "previous_valid_from": prev_valid_from,
                    "current_valid_from": cur_valid_from,
                    "previous_valid_to": prev_valid_to,
                    "current_valid_to": cur_valid_to,
                }
            )

        # New edges
        prev_edge_ids = set(previous.edges.keys())
        new_edges = []
        for eid, edge in current.edges.items():
            if eid not in prev_edge_ids:
                src = current.get_node(edge.source_id)
                tgt = current.get_node(edge.target_id)
                new_edges.append(
                    {
                        "source": src.label if src else edge.source_id,
                        "target": tgt.label if tgt else edge.target_id,
                        "relation": edge.relation,
                    }
                )

        # Drift score
        ds = drift_score(previous, current)

        # Contradictions newly introduced in current
        engine = ContradictionEngine()
        previous_contradiction_ids = {c.id for c in engine.detect_all(previous)}
        contradictions = [c for c in engine.detect_all(current) if c.id not in previous_contradiction_ids]
        contradiction_dicts = [
            {"type": c.type, "description": c.description, "severity": c.severity} for c in contradictions
        ]

        # Gaps in current
        analyzer = GapAnalyzer()
        gaps = analyzer.all_gaps(current)

        return {
            "new_nodes": new_nodes,
            "removed_nodes": removed_nodes,
            "confidence_changes": confidence_changes,
            "temporal_changes": temporal_changes,
            "new_edges": new_edges,
            "drift_score": ds,
            "new_contradictions": contradiction_dicts,
            "gaps": gaps,
        }
