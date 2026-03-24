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
from cortex.semantic_diff import semantic_diff_graphs

FAILURE_POLICIES = frozenset(
    {
        "none",
        "blocking",
        "contradictions",
        "temporal_gaps",
        "low_confidence",
        "retractions",
        "changes",
    }
)


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
    semantic_changes: list[dict[str, Any]]
    semantic_summary: dict[str, Any]

    def summary(self) -> dict[str, int]:
        blocking_issues = (
            len(self.new_contradictions)
            + len(self.new_temporal_gaps)
            + len(self.introduced_low_confidence_active_priorities)
        )
        return {
            "added_nodes": len(self.diff.get("added_nodes", [])),
            "removed_nodes": len(self.diff.get("removed_nodes", [])),
            "modified_nodes": len(self.diff.get("modified_nodes", [])),
            "new_contradictions": len(self.new_contradictions),
            "new_temporal_gaps": len(self.new_temporal_gaps),
            "introduced_low_confidence_active_priorities": len(self.introduced_low_confidence_active_priorities),
            "new_retractions": len(self.new_retractions),
            "blocking_issues": blocking_issues,
            "semantic_changes": len(self.semantic_changes),
        }

    def failure_counts(self) -> dict[str, int]:
        summary = self.summary()
        return {
            "blocking": summary["blocking_issues"],
            "contradictions": summary["new_contradictions"],
            "temporal_gaps": summary["new_temporal_gaps"],
            "low_confidence": summary["introduced_low_confidence_active_priorities"],
            "retractions": summary["new_retractions"],
            "changes": summary["added_nodes"] + summary["removed_nodes"] + summary["modified_nodes"],
        }

    def should_fail(self, policies: list[str]) -> tuple[bool, dict[str, int]]:
        counts = self.failure_counts()
        if not policies or policies == ["blocking"]:
            return counts["blocking"] > 0, counts
        if "none" in policies:
            return False, counts
        return any(counts.get(policy, 0) > 0 for policy in policies), counts

    def to_markdown(self, policies: list[str] | None = None) -> str:
        summary = self.summary()
        should_fail, counts = self.should_fail(policies or ["blocking"])
        lines = [
            "# Memory Review",
            "",
            f"- Current: `{self.current_label}`",
            f"- Against: `{self.against_label}`",
            f"- Status: `{'fail' if should_fail else 'pass'}`",
            f"- Added nodes: `{summary['added_nodes']}`",
            f"- Removed nodes: `{summary['removed_nodes']}`",
            f"- Modified nodes: `{summary['modified_nodes']}`",
            f"- New contradictions: `{summary['new_contradictions']}`",
            f"- New temporal gaps: `{summary['new_temporal_gaps']}`",
            f"- New low-confidence active priorities: `{summary['introduced_low_confidence_active_priorities']}`",
            f"- New retractions: `{summary['new_retractions']}`",
            f"- Semantic changes: `{summary['semantic_changes']}`",
            "",
            "## Failure Gates",
            "",
            *(f"- `{policy}`: `{counts[policy]}`" for policy in (policies or ["blocking"]) if policy in counts),
        ]

        if self.diff.get("added_nodes"):
            lines.extend(["", "## Added Nodes", ""])
            lines.extend(f"- `{item['label']}` (`{item['id']}`)" for item in self.diff["added_nodes"][:20])
        if self.diff.get("modified_nodes"):
            lines.extend(["", "## Modified Nodes", ""])
            lines.extend(
                f"- `{item['label']}`: {', '.join(sorted(item['changes']))}" for item in self.diff["modified_nodes"][:20]
            )
        if self.new_contradictions:
            lines.extend(["", "## New Contradictions", ""])
            lines.extend(f"- `{item['type']}`: {item['description']}" for item in self.new_contradictions[:20])
        if self.new_temporal_gaps:
            lines.extend(["", "## New Temporal Gaps", ""])
            lines.extend(f"- `{item['label']}`: `{item['kind']}`" for item in self.new_temporal_gaps[:20])
        if self.introduced_low_confidence_active_priorities:
            lines.extend(["", "## New Low-Confidence Active Priorities", ""])
            lines.extend(
                f"- `{item['label']}`: confidence `{item['confidence']}`"
                for item in self.introduced_low_confidence_active_priorities[:20]
            )
        if self.new_retractions:
            lines.extend(["", "## New Retractions", ""])
            lines.extend(
                f"- source `{item.get('source', '-')}` removed `{item.get('nodes_removed', 0)}` node(s)"
                for item in self.new_retractions[:20]
            )
        if self.semantic_changes:
            lines.extend(["", "## Semantic Changes", ""])
            lines.extend(
                f"- `{item['type']}`: {item['description']}"
                for item in self.semantic_changes[:20]
            )
        return "\n".join(lines).rstrip() + "\n"

    def to_dict(self) -> dict[str, Any]:
        summary = self.summary()
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
            "semantic_changes": list(self.semantic_changes),
            "semantic_summary": dict(self.semantic_summary),
            "summary": summary,
        }


def parse_failure_policies(spec: str) -> list[str]:
    parts = [item.strip() for item in spec.split(",") if item.strip()]
    policies = parts or ["blocking"]
    invalid = [item for item in policies if item not in FAILURE_POLICIES]
    if invalid:
        raise ValueError(f"Unknown review failure policy: {', '.join(invalid)}")
    if "none" in policies and len(policies) > 1:
        raise ValueError("Failure policy 'none' cannot be combined with other policies")
    return policies


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
    semantic = semantic_diff_graphs(baseline, current)

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
        semantic_changes=semantic["changes"],
        semantic_summary=semantic["summary"],
    )
