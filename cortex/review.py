"""
Review helpers for Git-for-AI-Memory workflows.

Compares a current graph against a baseline ref and summarizes structural
changes plus newly introduced memory risks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cortex.contradictions import ContradictionEngine
from cortex.graph import CortexGraph, diff_graphs
from cortex.intelligence import GapAnalyzer


def _gap_key(item: dict[str, Any]) -> str:
    return json.dumps(
        {
            "node_id": item.get("node_id"),
            "kind": item.get("kind"),
            "status": item.get("status"),
            "valid_from": item.get("valid_from"),
            "valid_to": item.get("valid_to"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _retraction_key(item: dict[str, Any]) -> str:
    return json.dumps(
        {
            "source": item.get("source"),
            "prune_orphans": item.get("prune_orphans"),
            "nodes_removed": item.get("nodes_removed"),
            "edges_removed": item.get("edges_removed"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


@dataclass
class ReviewResult:
    current_label: str
    against_label: str
    diff: dict[str, Any]
    new_contradictions: list[dict[str, Any]]
    resolved_contradictions: list[dict[str, Any]]
    new_temporal_gaps: list[dict[str, Any]]
    resolved_temporal_gaps: list[dict[str, Any]]
    low_confidence_active_priorities: list[dict[str, Any]]
    introduced_low_confidence_active_priorities: list[dict[str, Any]]
    new_retractions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        blocking_issues = (
            len(self.new_contradictions)
            + len(self.new_temporal_gaps)
            + len(self.introduced_low_confidence_active_priorities)
        )
        return {
            "current": self.current_label,
            "against": self.against_label,
            "diff": self.diff,
            "new_contradictions": list(self.new_contradictions),
            "resolved_contradictions": list(self.resolved_contradictions),
            "new_temporal_gaps": list(self.new_temporal_gaps),
            "resolved_temporal_gaps": list(self.resolved_temporal_gaps),
            "low_confidence_active_priorities": list(self.low_confidence_active_priorities),
            "introduced_low_confidence_active_priorities": list(self.introduced_low_confidence_active_priorities),
            "new_retractions": list(self.new_retractions),
            "summary": {
                "added_nodes": len(self.diff.get("added_nodes", [])),
                "removed_nodes": len(self.diff.get("removed_nodes", [])),
                "modified_nodes": len(self.diff.get("modified_nodes", [])),
                "new_contradictions": len(self.new_contradictions),
                "new_temporal_gaps": len(self.new_temporal_gaps),
                "introduced_low_confidence_active_priorities": len(self.introduced_low_confidence_active_priorities),
                "new_retractions": len(self.new_retractions),
                "blocking_issues": blocking_issues,
            },
        }


def review_graphs(current: CortexGraph, baseline: CortexGraph, *, current_label: str, against_label: str) -> ReviewResult:
    diff = diff_graphs(baseline, current)

    contradiction_engine = ContradictionEngine()
    current_contradictions = {item.id: item.to_dict() for item in contradiction_engine.detect_all(current)}
    baseline_contradictions = {item.id: item.to_dict() for item in contradiction_engine.detect_all(baseline)}
    new_contradictions = [current_contradictions[key] for key in sorted(set(current_contradictions) - set(baseline_contradictions))]
    resolved_contradictions = [
        baseline_contradictions[key] for key in sorted(set(baseline_contradictions) - set(current_contradictions))
    ]

    gap_analyzer = GapAnalyzer()
    current_temporal_gaps = { _gap_key(item): item for item in gap_analyzer.temporal_gaps(current) }
    baseline_temporal_gaps = { _gap_key(item): item for item in gap_analyzer.temporal_gaps(baseline) }
    new_temporal_gaps = [current_temporal_gaps[key] for key in sorted(set(current_temporal_gaps) - set(baseline_temporal_gaps))]
    resolved_temporal_gaps = [
        baseline_temporal_gaps[key] for key in sorted(set(baseline_temporal_gaps) - set(current_temporal_gaps))
    ]

    low_confidence_active_priorities = gap_analyzer.confidence_gaps(current)
    baseline_low_confidence = {item["node_id"]: item for item in gap_analyzer.confidence_gaps(baseline)}
    introduced_low_confidence_active_priorities = [
        item for item in low_confidence_active_priorities if item["node_id"] not in baseline_low_confidence
    ]

    current_retractions = {
        _retraction_key(item): item for item in current.meta.get("retractions", []) if isinstance(item, dict)
    }
    baseline_retractions = {
        _retraction_key(item): item for item in baseline.meta.get("retractions", []) if isinstance(item, dict)
    }
    new_retractions = [current_retractions[key] for key in sorted(set(current_retractions) - set(baseline_retractions))]

    return ReviewResult(
        current_label=current_label,
        against_label=against_label,
        diff=diff,
        new_contradictions=new_contradictions,
        resolved_contradictions=resolved_contradictions,
        new_temporal_gaps=new_temporal_gaps,
        resolved_temporal_gaps=resolved_temporal_gaps,
        low_confidence_active_priorities=low_confidence_active_priorities,
        introduced_low_confidence_active_priorities=introduced_low_confidence_active_priorities,
        new_retractions=new_retractions,
    )
