"""
Contradiction Engine — Detect conflicting knowledge in a CortexGraph (v5.1)

Five detector types:
1. Negation conflicts: same entity in positive tag + "negations" tag
2. Temporal flips: confidence changed direction >= 2 times across >= 3 snapshots
3. Source conflicts: same label from different sources with description mismatch
4. Tag conflicts: node moved between contradictory tags over time
5. Temporal claim conflicts: impossible validity windows or overlapping lifecycle claims
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cortex.graph.graph import CortexGraph, Node, _normalize_label

# Tags considered "positive" (non-negation)
_POSITIVE_TAGS = frozenset(
    {
        "identity",
        "professional_context",
        "business_context",
        "active_priorities",
        "relationships",
        "technical_expertise",
        "domain_knowledge",
        "market_context",
        "metrics",
        "constraints",
        "values",
        "user_preferences",
        "communication_preferences",
        "history",
        "mentions",
    }
)

# Tag pairs that are contradictory when a node moves between them
_CONTRADICTORY_TAG_PAIRS = [
    ("technical_expertise", "negations"),
    ("domain_knowledge", "negations"),
    ("values", "negations"),
    ("active_priorities", "negations"),
    ("professional_context", "negations"),
    ("identity", "negations"),
    ("user_preferences", "negations"),
]


@dataclass
class Contradiction:
    id: str
    type: str  # "negation_conflict", "temporal_flip", "source_conflict", "tag_conflict", "temporal_claim_conflict"
    node_ids: list[str]
    severity: float  # 0.0-1.0
    description: str
    detected_at: str  # ISO-8601
    resolution: str  # "prefer_newer", "prefer_higher_confidence", "needs_review"
    node_label: str = ""
    old_value: str = ""
    new_value: str = ""
    source_quotes: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "node_ids": list(self.node_ids),
            "severity": self.severity,
            "description": self.description,
            "detected_at": self.detected_at,
            "resolution": self.resolution,
            "node_label": self.node_label,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "source_quotes": list(self.source_quotes or []),
            "metadata": dict(self.metadata or {}),
        }


def _make_conflict_id(kind: str, node_ids: list[str], description: str) -> str:
    payload = f"{kind}:{','.join(sorted(node_ids))}:{description.strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


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


def _normalize_status(node: Node) -> str:
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


def _interval_bounds(node: Node) -> tuple[str, str]:
    start = _normalize_timestamp(getattr(node, "valid_from", "") or "")
    end = _normalize_timestamp(getattr(node, "valid_to", "") or "")
    return start, end


def _intervals_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    left = max(start_a or "", start_b or "")
    right_candidates = [value for value in (end_a, end_b) if value]
    right = min(right_candidates) if right_candidates else ""
    if not right:
        return True
    return left <= right


class ContradictionEngine:
    """Detect contradictions in a CortexGraph."""

    def detect_all(self, graph: CortexGraph, min_severity: float = 0.0) -> list[Contradiction]:
        """Run all 4 detectors, return sorted by severity desc."""
        results: list[Contradiction] = []
        results.extend(self.detect_negation_conflicts(graph))
        results.extend(self.detect_temporal_flips(graph))
        results.extend(self.detect_source_conflicts(graph))
        results.extend(self.detect_tag_conflicts(graph))
        results.extend(self.detect_temporal_claim_conflicts(graph))

        if min_severity > 0.0:
            results = [c for c in results if c.severity >= min_severity]

        results.sort(key=lambda c: c.severity, reverse=True)
        return results

    def detect_negation_conflicts(self, graph: CortexGraph) -> list[Contradiction]:
        """Same entity in positive tag + 'negations' tag.

        Finds nodes that have "negations" as one of their tags AND at least
        one positive tag. This indicates conflicting information.
        """
        contradictions: list[Contradiction] = []
        now = datetime.now(timezone.utc).isoformat()

        for node in graph.nodes.values():
            if "negations" not in node.tags:
                continue
            positive_tags = [t for t in node.tags if t in _POSITIVE_TAGS]
            if not positive_tags:
                continue

            severity = min(1.0, 0.6 + (node.confidence * 0.4))
            contradictions.append(
                Contradiction(
                    id=_make_conflict_id("negation_conflict", [node.id], node.label),
                    type="negation_conflict",
                    node_ids=[node.id],
                    severity=round(severity, 2),
                    description=(f"Node '{node.label}' has both negation and positive tags: {positive_tags}"),
                    detected_at=now,
                    resolution="needs_review",
                    node_label=node.label,
                    old_value=", ".join(positive_tags),
                    new_value="negations",
                    source_quotes=list(node.source_quotes),
                    metadata={"positive_tags": positive_tags},
                )
            )

        return contradictions

    def detect_temporal_flips(self, graph: CortexGraph) -> list[Contradiction]:
        """Confidence changed direction >= 2 times across >= 3 snapshots.

        Returns empty if a node has < 3 snapshots (insufficient data).
        """
        contradictions: list[Contradiction] = []
        now = datetime.now(timezone.utc).isoformat()
        min_confidence_delta = 0.05

        for node in graph.nodes.values():
            snapshots = node.snapshots if hasattr(node, "snapshots") else []
            if len(snapshots) < 3:
                continue

            # Sort snapshots by timestamp
            sorted_snaps = sorted(snapshots, key=lambda s: s.get("timestamp", ""))
            confidences = [s.get("confidence", 0.5) for s in sorted_snaps]
            snapshot_tags = [set(s.get("tags", [])) for s in sorted_snaps]

            # Treat semantic tag moves as tag conflicts, not temporal confidence flips.
            if any(tags != snapshot_tags[0] for tags in snapshot_tags[1:]):
                continue

            # Ignore small confidence noise and count only meaningful reversals.
            directions = []
            for i in range(1, len(confidences)):
                delta = confidences[i] - confidences[i - 1]
                if abs(delta) < min_confidence_delta:
                    continue
                directions.append(1 if delta > 0 else -1)

            direction_changes = sum(1 for i in range(1, len(directions)) if directions[i] != directions[i - 1])

            if direction_changes >= 2:
                severity = min(1.0, 0.4 + (direction_changes * 0.2))
                contradictions.append(
                    Contradiction(
                        id=_make_conflict_id("temporal_flip", [node.id], node.label),
                        type="temporal_flip",
                        node_ids=[node.id],
                        severity=round(severity, 2),
                        description=(
                            f"Node '{node.label}' confidence flipped direction "
                            f"{direction_changes} times across {len(snapshots)} snapshots"
                        ),
                        detected_at=now,
                        resolution="prefer_newer",
                        node_label=node.label,
                        old_value=str(confidences[0]),
                        new_value=str(confidences[-1]),
                        source_quotes=list(node.source_quotes),
                        metadata={
                            "direction_changes": direction_changes,
                            "first_confidence": confidences[0],
                            "last_confidence": confidences[-1],
                            "latest_timestamp": sorted_snaps[-1].get("timestamp", ""),
                            "earliest_timestamp": sorted_snaps[0].get("timestamp", ""),
                        },
                    )
                )

        return contradictions

    def detect_source_conflicts(self, graph: CortexGraph) -> list[Contradiction]:
        """Same label from different source files with description_hash mismatch.

        Groups nodes by normalized label, checks if snapshots from different
        sources have different description hashes.
        """
        contradictions: list[Contradiction] = []
        now = datetime.now(timezone.utc).isoformat()

        # Group nodes by normalized label
        label_groups: dict[str, list[Node]] = {}
        for node in graph.nodes.values():
            norm = _normalize_label(node.label)
            label_groups.setdefault(norm, []).append(node)

        for norm_label, nodes in label_groups.items():
            if len(nodes) < 2:
                continue

            # Collect latest description hash per source (by timestamp)
            source_latest: dict[str, tuple[str, str]] = {}  # source -> (timestamp, hash)
            for node in nodes:
                snapshots = node.snapshots if hasattr(node, "snapshots") else []
                for snap in snapshots:
                    source = snap.get("source", "unknown")
                    desc_hash = snap.get("description_hash", "")
                    ts = snap.get("timestamp", "")
                    if desc_hash:
                        prev = source_latest.get(source)
                        if prev is None or ts > prev[0]:
                            source_latest[source] = (ts, desc_hash)

            # Only flag when different sources disagree (not temporal changes within one source)
            if len(source_latest) < 2:
                continue
            per_source_latest = {src: pair[1] for src, pair in source_latest.items()}
            unique_hashes = set(per_source_latest.values())
            if len(unique_hashes) >= 2:
                node_ids = [n.id for n in nodes]
                newest_node = max(
                    nodes,
                    key=lambda n: max((snap.get("timestamp", "") for snap in n.snapshots), default=""),
                )
                oldest_node = min(
                    nodes,
                    key=lambda n: min((snap.get("timestamp", "") for snap in n.snapshots), default=""),
                )
                severity = min(1.0, 0.5 + (len(unique_hashes) * 0.15))
                contradictions.append(
                    Contradiction(
                        id=_make_conflict_id("source_conflict", node_ids, nodes[0].label),
                        type="source_conflict",
                        node_ids=node_ids,
                        severity=round(severity, 2),
                        description=(
                            f"Label '{nodes[0].label}' has {len(unique_hashes)} different "
                            f"descriptions across {len(nodes)} nodes/sources"
                        ),
                        detected_at=now,
                        resolution="prefer_higher_confidence",
                        node_label=nodes[0].label,
                        source_quotes=list(nodes[0].source_quotes),
                        metadata={
                            "sources": sorted(source_latest),
                            "hashes": sorted(unique_hashes),
                            "newest_node_id": newest_node.id,
                            "oldest_node_id": oldest_node.id,
                        },
                    )
                )

        return contradictions

    def detect_tag_conflicts(self, graph: CortexGraph) -> list[Contradiction]:
        """Node moved between contradictory tags over time.

        Checks snapshots for tag changes where a node was previously in a
        positive tag and later moved to "negations" (or vice versa).
        """
        contradictions: list[Contradiction] = []
        now = datetime.now(timezone.utc).isoformat()

        for node in graph.nodes.values():
            snapshots = node.snapshots if hasattr(node, "snapshots") else []
            if len(snapshots) < 2:
                continue

            sorted_snaps = sorted(snapshots, key=lambda s: s.get("timestamp", ""))
            latest_conflict: tuple[float, str, str] | None = None

            # Collect all tags seen across snapshots
            for i in range(len(sorted_snaps) - 1):
                tags_before = set(sorted_snaps[i].get("tags", []))
                tags_after = set(sorted_snaps[i + 1].get("tags", []))

                for pos_tag, neg_tag in _CONTRADICTORY_TAG_PAIRS:
                    # Was in positive, moved to negation
                    if pos_tag in tags_before and neg_tag in tags_after and neg_tag not in tags_before:
                        latest_conflict = (0.7, pos_tag, neg_tag)
                    # Was in negation, moved to positive
                    elif neg_tag in tags_before and pos_tag in tags_after and pos_tag not in tags_before:
                        latest_conflict = (0.6, neg_tag, pos_tag)

            if latest_conflict is not None:
                severity, old_tag, new_tag = latest_conflict
                contradictions.append(
                    Contradiction(
                        id=_make_conflict_id("tag_conflict", [node.id], f"{node.label}:{old_tag}:{new_tag}"),
                        type="tag_conflict",
                        node_ids=[node.id],
                        severity=severity,
                        description=(f"Node '{node.label}' moved from '{old_tag}' to '{new_tag}' between snapshots"),
                        detected_at=now,
                        resolution="prefer_newer",
                        node_label=node.label,
                        old_value=old_tag,
                        new_value=new_tag,
                        source_quotes=list(node.source_quotes),
                    )
                )

        return contradictions

    def detect_temporal_claim_conflicts(self, graph: CortexGraph) -> list[Contradiction]:
        """Detect invalid windows and overlapping incompatible lifecycle claims."""
        contradictions: list[Contradiction] = []
        now = datetime.now(timezone.utc).isoformat()

        label_groups: dict[str, list[Node]] = {}
        for node in graph.nodes.values():
            norm = _normalize_label(node.label)
            label_groups.setdefault(norm, []).append(node)

        for node in graph.nodes.values():
            valid_from, valid_to = _interval_bounds(node)
            if valid_from and valid_to and valid_to < valid_from:
                contradictions.append(
                    Contradiction(
                        id=_make_conflict_id("temporal_claim_conflict", [node.id], f"{node.label}:invalid-window"),
                        type="temporal_claim_conflict",
                        node_ids=[node.id],
                        severity=0.95,
                        description=(
                            f"Node '{node.label}' has an invalid validity window: "
                            f"valid_to ({valid_to}) is earlier than valid_from ({valid_from})"
                        ),
                        detected_at=now,
                        resolution="needs_review",
                        node_label=node.label,
                        old_value=valid_from,
                        new_value=valid_to,
                        source_quotes=list(node.source_quotes),
                        metadata={
                            "reason": "invalid_window",
                            "status": _normalize_status(node),
                            "valid_from": valid_from,
                            "valid_to": valid_to,
                        },
                    )
                )

        incompatible_pairs = {
            tuple(sorted(("planned", "active"))),
            tuple(sorted(("planned", "historical"))),
            tuple(sorted(("active", "historical"))),
        }

        for nodes in label_groups.values():
            if len(nodes) < 2:
                continue
            for i in range(len(nodes) - 1):
                for j in range(i + 1, len(nodes)):
                    node_a = nodes[i]
                    node_b = nodes[j]
                    status_a = _normalize_status(node_a)
                    status_b = _normalize_status(node_b)
                    if not status_a or not status_b or status_a == status_b:
                        continue
                    pair = tuple(sorted((status_a, status_b)))
                    if pair not in incompatible_pairs:
                        continue

                    start_a, end_a = _interval_bounds(node_a)
                    start_b, end_b = _interval_bounds(node_b)
                    if not _intervals_overlap(start_a, end_a, start_b, end_b):
                        continue

                    severity = 0.85 if pair == ("active", "historical") else 0.75
                    contradictions.append(
                        Contradiction(
                            id=_make_conflict_id(
                                "temporal_claim_conflict",
                                [node_a.id, node_b.id],
                                f"{node_a.label}:{status_a}:{status_b}:{start_a}:{end_a}:{start_b}:{end_b}",
                            ),
                            type="temporal_claim_conflict",
                            node_ids=[node_a.id, node_b.id],
                            severity=severity,
                            description=(
                                f"Label '{node_a.label}' has overlapping temporal claims with incompatible "
                                f"statuses: {status_a} vs {status_b}"
                            ),
                            detected_at=now,
                            resolution="needs_review",
                            node_label=node_a.label,
                            old_value=status_a,
                            new_value=status_b,
                            source_quotes=list(dict.fromkeys(node_a.source_quotes + node_b.source_quotes)),
                            metadata={
                                "reason": "overlapping_status_claims",
                                "node_a": {
                                    "id": node_a.id,
                                    "status": status_a,
                                    "valid_from": start_a,
                                    "valid_to": end_a,
                                },
                                "node_b": {
                                    "id": node_b.id,
                                    "status": status_b,
                                    "valid_from": start_b,
                                    "valid_to": end_b,
                                },
                            },
                        )
                    )

        return contradictions
