"""
Contradiction Engine — Detect conflicting knowledge in a CortexGraph (v5.1)

Four detector types:
1. Negation conflicts: same entity in positive tag + "negations" tag
2. Temporal flips: confidence changed direction >= 2 times across >= 3 snapshots
3. Source conflicts: same label from different sources with description mismatch
4. Tag conflicts: node moved between contradictory tags over time
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from cortex.graph import CortexGraph, Node, _normalize_label


# Tags considered "positive" (non-negation)
_POSITIVE_TAGS = frozenset({
    "identity", "professional_context", "business_context", "active_priorities",
    "relationships", "technical_expertise", "domain_knowledge", "market_context",
    "metrics", "constraints", "values", "user_preferences",
    "communication_preferences", "history", "mentions",
})

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
    type: str            # "negation_conflict", "temporal_flip", "source_conflict", "tag_conflict"
    node_ids: list[str]
    severity: float      # 0.0-1.0
    description: str
    detected_at: str     # ISO-8601
    resolution: str      # "prefer_newer", "prefer_higher_confidence", "needs_review"


class ContradictionEngine:
    """Detect contradictions in a CortexGraph."""

    def detect_all(self, graph: CortexGraph, min_severity: float = 0.0) -> list[Contradiction]:
        """Run all 4 detectors, return sorted by severity desc."""
        results: list[Contradiction] = []
        results.extend(self.detect_negation_conflicts(graph))
        results.extend(self.detect_temporal_flips(graph))
        results.extend(self.detect_source_conflicts(graph))
        results.extend(self.detect_tag_conflicts(graph))

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
            contradictions.append(Contradiction(
                type="negation_conflict",
                node_ids=[node.id],
                severity=round(severity, 2),
                description=(
                    f"Node '{node.label}' has both negation and positive tags: "
                    f"{positive_tags}"
                ),
                detected_at=now,
                resolution="needs_review",
            ))

        return contradictions

    def detect_temporal_flips(self, graph: CortexGraph) -> list[Contradiction]:
        """Confidence changed direction >= 2 times across >= 3 snapshots.

        Returns empty if a node has < 3 snapshots (insufficient data).
        """
        contradictions: list[Contradiction] = []
        now = datetime.now(timezone.utc).isoformat()

        for node in graph.nodes.values():
            snapshots = node.snapshots if hasattr(node, "snapshots") else []
            if len(snapshots) < 3:
                continue

            # Sort snapshots by timestamp
            sorted_snaps = sorted(snapshots, key=lambda s: s.get("timestamp", ""))
            confidences = [s.get("confidence", 0.5) for s in sorted_snaps]

            # Count direction changes
            direction_changes = 0
            for i in range(2, len(confidences)):
                prev_dir = confidences[i - 1] - confidences[i - 2]
                curr_dir = confidences[i] - confidences[i - 1]
                if (prev_dir > 0 and curr_dir < 0) or (prev_dir < 0 and curr_dir > 0):
                    direction_changes += 1

            if direction_changes >= 2:
                severity = min(1.0, 0.4 + (direction_changes * 0.2))
                contradictions.append(Contradiction(
                    type="temporal_flip",
                    node_ids=[node.id],
                    severity=round(severity, 2),
                    description=(
                        f"Node '{node.label}' confidence flipped direction "
                        f"{direction_changes} times across {len(snapshots)} snapshots"
                    ),
                    detected_at=now,
                    resolution="prefer_newer",
                ))

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

            # Collect unique description hashes across nodes
            desc_hashes: dict[str, str] = {}  # node_id -> description_hash
            for node in nodes:
                snapshots = node.snapshots if hasattr(node, "snapshots") else []
                for snap in snapshots:
                    source = snap.get("source", "unknown")
                    desc_hash = snap.get("description_hash", "")
                    key = f"{node.id}:{source}"
                    if desc_hash:
                        desc_hashes[key] = desc_hash

            # If we have hashes from different sources that disagree
            unique_hashes = set(desc_hashes.values())
            if len(unique_hashes) >= 2:
                node_ids = [n.id for n in nodes]
                severity = min(1.0, 0.5 + (len(unique_hashes) * 0.15))
                contradictions.append(Contradiction(
                    type="source_conflict",
                    node_ids=node_ids,
                    severity=round(severity, 2),
                    description=(
                        f"Label '{nodes[0].label}' has {len(unique_hashes)} different "
                        f"descriptions across {len(nodes)} nodes/sources"
                    ),
                    detected_at=now,
                    resolution="prefer_higher_confidence",
                ))

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

            # Collect all tags seen across snapshots
            for i in range(len(sorted_snaps) - 1):
                tags_before = set(sorted_snaps[i].get("tags", []))
                tags_after = set(sorted_snaps[i + 1].get("tags", []))

                for pos_tag, neg_tag in _CONTRADICTORY_TAG_PAIRS:
                    # Was in positive, moved to negation
                    if pos_tag in tags_before and neg_tag in tags_after and neg_tag not in tags_before:
                        severity = 0.7
                        contradictions.append(Contradiction(
                            type="tag_conflict",
                            node_ids=[node.id],
                            severity=severity,
                            description=(
                                f"Node '{node.label}' moved from '{pos_tag}' to "
                                f"'{neg_tag}' between snapshots"
                            ),
                            detected_at=now,
                            resolution="prefer_newer",
                        ))
                        break
                    # Was in negation, moved to positive
                    if neg_tag in tags_before and pos_tag in tags_after and pos_tag not in tags_before:
                        severity = 0.6
                        contradictions.append(Contradiction(
                            type="tag_conflict",
                            node_ids=[node.id],
                            severity=severity,
                            description=(
                                f"Node '{node.label}' moved from '{neg_tag}' to "
                                f"'{pos_tag}' between snapshots"
                            ),
                            detected_at=now,
                            resolution="prefer_newer",
                        ))
                        break

        return contradictions
