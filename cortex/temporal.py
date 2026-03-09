"""
Temporal Engine — Snapshots + Identity Drift Scoring (v5.1)

Snapshots capture lightweight point-in-time state of nodes.
Drift scoring computes weighted Jaccard distance between two graphs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from cortex.graph import CortexGraph, Node

# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass
class Snapshot:
    timestamp: str  # ISO-8601
    source: str  # "extraction", "merge", "manual"
    confidence: float  # node's confidence at this point
    tags: list[str]  # node's tags at this point
    properties_hash: str  # sha256 of sorted properties dict
    description_hash: str  # sha256 of full_description


def _hash_dict(d: dict) -> str:
    """SHA-256 of JSON-serialized sorted dict."""
    raw = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _hash_str(s: str) -> str:
    """SHA-256 of a string (first 16 hex chars)."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def create_snapshot_dict(node: Node, source: str, timestamp: str | None = None) -> dict:
    """Create a lightweight snapshot dict from current node state."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "timestamp": timestamp,
        "source": source,
        "confidence": round(node.confidence, 2),
        "tags": list(node.tags),
        "properties_hash": _hash_dict(node.properties),
        "description_hash": _hash_str(node.full_description),
    }


def snapshot_from_dict(d: dict) -> Snapshot:
    """Convert a snapshot dict back to a Snapshot dataclass."""
    return Snapshot(
        timestamp=d["timestamp"],
        source=d["source"],
        confidence=d["confidence"],
        tags=list(d["tags"]),
        properties_hash=d["properties_hash"],
        description_hash=d["description_hash"],
    )


# ---------------------------------------------------------------------------
# Drift Scoring
# ---------------------------------------------------------------------------

# Category weights for drift calculation
DRIFT_WEIGHTS: dict[str, float] = {
    "identity": 3.0,
    "values": 2.0,
    "professional_context": 2.0,
}
_DEFAULT_WEIGHT = 1.0


def _weighted_jaccard(set_a: set[str], set_b: set[str], weights: dict[str, float]) -> float:
    """Weighted Jaccard distance: 1 - weighted_intersection / weighted_union.

    Returns 0.0 for identical sets, 1.0 for completely disjoint sets.
    Returns 0.0 if both sets are empty.
    """
    if not set_a and not set_b:
        return 0.0

    union = set_a | set_b
    intersection = set_a & set_b

    w_union = sum(weights.get(item, _DEFAULT_WEIGHT) for item in union)
    w_intersection = sum(weights.get(item, _DEFAULT_WEIGHT) for item in intersection)

    if w_union == 0:
        return 0.0

    return 1.0 - (w_intersection / w_union)


def drift_score(graph_a: CortexGraph, graph_b: CortexGraph) -> dict:
    """Compute identity drift between two graphs.

    Returns:
        {
            "score": float (0.0 = identical, 1.0 = completely different),
            "details": {
                "label_drift": float,
                "tag_drift": float,
                "confidence_drift": float,
                "node_count_a": int,
                "node_count_b": int,
            },
            "sufficient_data": bool,
        }

    Returns sufficient_data=False if either graph has < 3 nodes.
    """
    nodes_a = graph_a.nodes
    nodes_b = graph_b.nodes

    if len(nodes_a) < 3 or len(nodes_b) < 3:
        return {
            "score": None,
            "details": {
                "label_drift": None,
                "tag_drift": None,
                "confidence_drift": None,
                "node_count_a": len(nodes_a),
                "node_count_b": len(nodes_b),
            },
            "sufficient_data": False,
        }

    # Label drift: weighted Jaccard on node labels
    labels_a = {n.label.lower().strip() for n in nodes_a.values()}
    labels_b = {n.label.lower().strip() for n in nodes_b.values()}
    label_drift = _weighted_jaccard(labels_a, labels_b, {})

    # Tag drift: weighted Jaccard on all unique tags
    tags_a: set[str] = set()
    tags_b: set[str] = set()
    for n in nodes_a.values():
        tags_a.update(n.tags)
    for n in nodes_b.values():
        tags_b.update(n.tags)
    tag_drift = _weighted_jaccard(tags_a, tags_b, DRIFT_WEIGHTS)

    # Confidence drift: average absolute confidence difference for shared labels
    shared_labels = labels_a & labels_b
    if shared_labels:
        conf_a = {}
        conf_b = {}
        for n in nodes_a.values():
            key = n.label.lower().strip()
            if key in shared_labels:
                conf_a[key] = max(conf_a.get(key, 0.0), n.confidence)
        for n in nodes_b.values():
            key = n.label.lower().strip()
            if key in shared_labels:
                conf_b[key] = max(conf_b.get(key, 0.0), n.confidence)
        total_diff = sum(abs(conf_a[k] - conf_b.get(k, 0.0)) for k in conf_a)
        confidence_drift = total_diff / len(shared_labels)
    else:
        confidence_drift = 1.0

    # Composite score: weighted average of components
    score = (label_drift * 0.5) + (tag_drift * 0.3) + (confidence_drift * 0.2)

    return {
        "score": round(score, 4),
        "details": {
            "label_drift": round(label_drift, 4),
            "tag_drift": round(tag_drift, 4),
            "confidence_drift": round(confidence_drift, 4),
            "node_count_a": len(nodes_a),
            "node_count_b": len(nodes_b),
        },
        "sufficient_data": True,
    }
