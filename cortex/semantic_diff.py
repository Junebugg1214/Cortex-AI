"""
Semantic diff helpers for Git-for-AI-Memory workflows.

These surface meaning-level shifts between two graphs, not just structural
add/remove/modify events.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from cortex.contradictions import ContradictionEngine
from cortex.graph import CortexGraph


def _source_set(node) -> list[str]:
    values = {
        str(item.get("source", "")).strip()
        for item in list(getattr(node, "provenance", [])) + list(getattr(node, "snapshots", []))
        if str(item.get("source", "")).strip()
    }
    return sorted(values)


def _push_change(
    changes: list[dict[str, Any]], *, change_type: str, severity: str, description: str, **payload: Any
) -> None:
    changes.append(
        {
            "type": change_type,
            "severity": severity,
            "description": description,
            **payload,
        }
    )


def semantic_diff_graphs(old: CortexGraph, new: CortexGraph) -> dict[str, Any]:
    """Return meaning-level changes between two graphs."""
    changes: list[dict[str, Any]] = []

    old_ids = set(old.nodes)
    new_ids = set(new.nodes)

    for node_id in sorted(new_ids - old_ids):
        node = new.nodes[node_id]
        _push_change(
            changes,
            change_type="belief_added",
            severity="medium",
            description=f"New belief '{node.label}' was introduced.",
            node_id=node.id,
            label=node.label,
            tags=list(node.tags),
        )

    for node_id in sorted(old_ids - new_ids):
        node = old.nodes[node_id]
        _push_change(
            changes,
            change_type="belief_removed",
            severity="high",
            description=f"Belief '{node.label}' was removed.",
            node_id=node.id,
            label=node.label,
            tags=list(node.tags),
        )

    for node_id in sorted(old_ids & new_ids):
        before = old.nodes[node_id]
        after = new.nodes[node_id]

        if before.label != after.label:
            _push_change(
                changes,
                change_type="identity_rename",
                severity="medium",
                description=f"Identity label changed from '{before.label}' to '{after.label}'.",
                node_id=node_id,
                label=after.label,
                from_value=before.label,
                to_value=after.label,
            )

        if before.status != after.status:
            _push_change(
                changes,
                change_type="lifecycle_shift",
                severity="high",
                description=f"Lifecycle for '{after.label}' changed from '{before.status or 'unspecified'}' to '{after.status or 'unspecified'}'.",
                node_id=node_id,
                label=after.label,
                from_value=before.status,
                to_value=after.status,
            )

        if before.valid_from != after.valid_from or before.valid_to != after.valid_to:
            _push_change(
                changes,
                change_type="temporal_window_shift",
                severity="high",
                description=f"Validity window for '{after.label}' changed.",
                node_id=node_id,
                label=after.label,
                from_value={"valid_from": before.valid_from, "valid_to": before.valid_to},
                to_value={"valid_from": after.valid_from, "valid_to": after.valid_to},
            )

        if sorted(before.tags) != sorted(after.tags):
            _push_change(
                changes,
                change_type="belief_category_shift",
                severity="medium",
                description=f"Tag/category meaning for '{after.label}' changed.",
                node_id=node_id,
                label=after.label,
                from_value=sorted(before.tags),
                to_value=sorted(after.tags),
            )

        confidence_delta = round(after.confidence - before.confidence, 4)
        if abs(confidence_delta) >= 0.2:
            _push_change(
                changes,
                change_type="confidence_shift",
                severity="medium",
                description=f"Confidence for '{after.label}' shifted by {confidence_delta:+.2f}.",
                node_id=node_id,
                label=after.label,
                delta=confidence_delta,
                from_value=before.confidence,
                to_value=after.confidence,
            )

        before_sources = _source_set(before)
        after_sources = _source_set(after)
        if before_sources != after_sources:
            _push_change(
                changes,
                change_type="provenance_shift",
                severity="medium",
                description=f"Source provenance for '{after.label}' changed.",
                node_id=node_id,
                label=after.label,
                from_value=before_sources,
                to_value=after_sources,
            )

    old_edge_ids = set(old.edges)
    new_edge_ids = set(new.edges)
    for edge_id in sorted(new_edge_ids - old_edge_ids):
        edge = new.edges[edge_id]
        src = new.nodes.get(edge.source_id)
        dst = new.nodes.get(edge.target_id)
        _push_change(
            changes,
            change_type="relationship_added",
            severity="low",
            description=f"Relationship '{edge.relation}' was added between '{src.label if src else edge.source_id}' and '{dst.label if dst else edge.target_id}'.",
            edge_id=edge_id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
        )

    for edge_id in sorted(old_edge_ids - new_edge_ids):
        edge = old.edges[edge_id]
        src = old.nodes.get(edge.source_id)
        dst = old.nodes.get(edge.target_id)
        _push_change(
            changes,
            change_type="relationship_removed",
            severity="medium",
            description=f"Relationship '{edge.relation}' was removed between '{src.label if src else edge.source_id}' and '{dst.label if dst else edge.target_id}'.",
            edge_id=edge_id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
        )

    contradiction_engine = ContradictionEngine()
    old_contradictions = {item.id: item for item in contradiction_engine.detect_all(old)}
    new_contradictions = {item.id: item for item in contradiction_engine.detect_all(new)}

    for key in sorted(set(new_contradictions) - set(old_contradictions)):
        item = new_contradictions[key]
        _push_change(
            changes,
            change_type="contradiction_introduced",
            severity="high",
            description=item.description,
            contradiction_id=item.id,
            contradiction_type=item.type,
            node_ids=list(item.node_ids),
        )

    for key in sorted(set(old_contradictions) - set(new_contradictions)):
        item = old_contradictions[key]
        _push_change(
            changes,
            change_type="contradiction_resolved",
            severity="medium",
            description=item.description,
            contradiction_id=item.id,
            contradiction_type=item.type,
            node_ids=list(item.node_ids),
        )

    counts = Counter(change["type"] for change in changes)
    severities = Counter(change["severity"] for change in changes)
    return {
        "changes": changes,
        "summary": {
            "total": len(changes),
            "by_type": dict(sorted(counts.items())),
            "by_severity": dict(sorted(severities.items())),
        },
    }
