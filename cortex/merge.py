"""
Memory merge support for Git-for-AI-Memory workflows.

Provides a small three-way merge engine over Cortex graphs with conflict
detection for incompatible concurrent edits.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cortex.contradictions import ContradictionEngine
from cortex.graph import CortexGraph, Edge, Node, _dedupe_dict_items, diff_graphs
from cortex.upai.versioning import VersionStore


def _node_payload(node: Node | None) -> dict[str, Any] | None:
    if node is None:
        return None
    return node.to_dict()


def _edge_payload(edge: Edge | None) -> dict[str, Any] | None:
    if edge is None:
        return None
    return edge.to_dict()


def _clone_graph(graph: CortexGraph) -> CortexGraph:
    return CortexGraph.from_v5_json(graph.export_v5())


def _field_value(node: Node, field_name: str) -> Any:
    value = getattr(node, field_name)
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def _field_changed(base: Node | None, node: Node | None, field_name: str) -> bool:
    if base is None or node is None:
        return base is not node
    return _field_value(base, field_name) != _field_value(node, field_name)


def _combine_lists(*values: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for value in values:
        for item in value:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, dict) else repr(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(copy.deepcopy(item))
    return merged


@dataclass
class MergeConflict:
    kind: str
    node_id: str = ""
    label: str = ""
    field: str = ""
    current: Any = None
    incoming: Any = None
    description: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "node_id": self.node_id,
            "label": self.label,
            "field": self.field,
            "current": self.current,
            "incoming": self.incoming,
            "description": self.description,
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class MergeResult:
    base_version: str | None
    current_version: str | None
    other_version: str | None
    merged: CortexGraph
    conflicts: list[MergeConflict]
    summary: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.conflicts


def _merge_scalar(
    field_name: str,
    base: Node | None,
    current: Node,
    other: Node,
    *,
    conflict_fields: set[str],
) -> tuple[Any, MergeConflict | None]:
    current_value = _field_value(current, field_name)
    other_value = _field_value(other, field_name)
    if current_value == other_value:
        return copy.deepcopy(current_value), None

    base_value = _field_value(base, field_name) if base is not None else None
    current_changed = base is None or current_value != base_value
    other_changed = base is None or other_value != base_value

    if current_changed and not other_changed:
        return copy.deepcopy(current_value), None
    if other_changed and not current_changed:
        return copy.deepcopy(other_value), None
    if not current_changed and not other_changed:
        return copy.deepcopy(current_value), None

    if field_name == "confidence":
        return max(float(current_value or 0.0), float(other_value or 0.0)), None

    if field_name in conflict_fields:
        conflict = MergeConflict(
            kind="field_conflict",
            node_id=current.id,
            label=current.label,
            field=field_name,
            current=current_value,
            incoming=other_value,
            description=f"Both branches changed '{current.label}' field '{field_name}' to incompatible values.",
        )
        return copy.deepcopy(current_value), conflict

    return copy.deepcopy(other_value), None


def _merge_node(base: Node | None, current: Node, other: Node) -> tuple[Node, list[MergeConflict]]:
    merged = copy.deepcopy(current)
    conflicts: list[MergeConflict] = []

    merged.tags = _combine_lists(current.tags, other.tags)
    merged.aliases = _combine_lists(current.aliases, other.aliases)
    merged.metrics = _combine_lists(current.metrics, other.metrics)
    merged.timeline = _combine_lists(current.timeline, other.timeline)
    merged.source_quotes = _combine_lists(current.source_quotes, other.source_quotes)
    merged.provenance = _dedupe_dict_items(list(current.provenance) + list(other.provenance))
    merged.snapshots = _dedupe_dict_items(list(current.snapshots) + list(other.snapshots))
    merged.properties = {**copy.deepcopy(other.properties), **copy.deepcopy(current.properties)}

    conflict_fields = {"label", "brief", "full_description", "status", "valid_from", "valid_to", "relationship_type"}
    scalar_fields = [
        "label",
        "confidence",
        "brief",
        "full_description",
        "mention_count",
        "extraction_method",
        "first_seen",
        "last_seen",
        "valid_from",
        "valid_to",
        "status",
        "relationship_type",
    ]
    for field_name in scalar_fields:
        value, conflict = _merge_scalar(field_name, base, current, other, conflict_fields=conflict_fields)
        setattr(merged, field_name, value)
        if conflict:
            conflicts.append(conflict)

    if current.canonical_id == other.canonical_id:
        merged.canonical_id = current.canonical_id or other.canonical_id or current.id
    elif base and base.canonical_id == current.canonical_id:
        merged.canonical_id = other.canonical_id or current.canonical_id or current.id
    elif base and base.canonical_id == other.canonical_id:
        merged.canonical_id = current.canonical_id or other.canonical_id or current.id
    else:
        conflicts.append(
            MergeConflict(
                kind="field_conflict",
                node_id=current.id,
                label=current.label,
                field="canonical_id",
                current=current.canonical_id,
                incoming=other.canonical_id,
                description=f"Branches disagree on canonical identity for '{current.label}'.",
            )
        )
        merged.canonical_id = current.canonical_id or other.canonical_id or current.id

    return merged, conflicts


def _merge_edges(current: CortexGraph, other: CortexGraph) -> dict[str, Edge]:
    edges = {eid: copy.deepcopy(edge) for eid, edge in current.edges.items()}
    for eid, edge in other.edges.items():
        if eid not in edges:
            edges[eid] = copy.deepcopy(edge)
            continue
        merged = edges[eid]
        merged.provenance = _dedupe_dict_items(list(merged.provenance) + list(edge.provenance))
        if not merged.description and edge.description:
            merged.description = edge.description
        if edge.confidence > merged.confidence:
            merged.confidence = edge.confidence
    return edges


def merge_graphs(base: CortexGraph, current: CortexGraph, other: CortexGraph) -> MergeResult:
    merged = _clone_graph(current)
    conflicts: list[MergeConflict] = []
    touched_node_ids: set[str] = set()

    for node_id in sorted(set(base.nodes) | set(current.nodes) | set(other.nodes)):
        base_node = base.nodes.get(node_id)
        current_node = current.nodes.get(node_id)
        other_node = other.nodes.get(node_id)

        if current_node is None and other_node is None:
            continue
        if current_node is None and other_node is not None:
            if base_node is not None:
                conflicts.append(
                    MergeConflict(
                        kind="delete_modify_conflict",
                        node_id=node_id,
                        label=other_node.label,
                        description=f"'{other_node.label}' was removed on the current branch but still exists on the incoming branch.",
                    )
                )
                continue
            merged.add_node(copy.deepcopy(other_node))
            touched_node_ids.add(node_id)
            continue
        if current_node is not None and other_node is None:
            if base_node is not None:
                conflicts.append(
                    MergeConflict(
                        kind="delete_modify_conflict",
                        node_id=node_id,
                        label=current_node.label,
                        description=f"'{current_node.label}' was removed on the incoming branch but still exists on the current branch.",
                    )
                )
            continue

        assert current_node is not None and other_node is not None
        if _node_payload(current_node) == _node_payload(other_node):
            continue
        if base_node is not None and _node_payload(current_node) == _node_payload(base_node):
            merged.nodes[node_id] = copy.deepcopy(other_node)
            touched_node_ids.add(node_id)
            continue
        if base_node is not None and _node_payload(other_node) == _node_payload(base_node):
            continue

        merged_node, node_conflicts = _merge_node(base_node, current_node, other_node)
        merged.nodes[node_id] = merged_node
        touched_node_ids.add(node_id)
        conflicts.extend(node_conflicts)

    merged.edges = _merge_edges(current, other)
    merged.meta.setdefault("merge_history", []).append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conflict_count": len(conflicts),
            "touched_node_ids": sorted(touched_node_ids),
        }
    )

    engine = ContradictionEngine()
    current_ids = {item.id for item in engine.detect_all(current)}
    other_ids = {item.id for item in engine.detect_all(other)}
    for contradiction in engine.detect_all(merged):
        if contradiction.id in current_ids or contradiction.id in other_ids:
            continue
        if touched_node_ids and not (set(contradiction.node_ids) & touched_node_ids):
            continue
        conflicts.append(
            MergeConflict(
                kind="contradiction_conflict",
                node_id=contradiction.node_ids[0] if contradiction.node_ids else "",
                label=contradiction.node_label,
                field=contradiction.type,
                description=contradiction.description,
                metadata=contradiction.to_dict(),
            )
        )

    summary = diff_graphs(current, merged)
    summary["conflicts"] = len(conflicts)
    summary["touched_nodes"] = len(touched_node_ids)
    return MergeResult(
        base_version=None,
        current_version=None,
        other_version=None,
        merged=merged,
        conflicts=conflicts,
        summary=summary,
    )


def merge_refs(store: VersionStore, current_ref: str, other_ref: str) -> MergeResult:
    base_id = store.merge_base(current_ref, other_ref)
    current_id = store.resolve_ref(current_ref)
    other_id = store.resolve_ref(other_ref)
    if not other_id:
        raise ValueError(f"Branch or ref not found: {other_ref}")

    base_graph = store.checkout(base_id) if base_id else CortexGraph()
    current_graph = store.checkout(current_id) if current_id else CortexGraph()
    other_graph = store.checkout(other_id) if other_id else CortexGraph()

    result = merge_graphs(base_graph, current_graph, other_graph)
    result.base_version = base_id
    result.current_version = current_id
    result.other_version = other_id
    return result
