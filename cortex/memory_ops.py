from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cortex.contradictions import ContradictionEngine
from cortex.graph import CortexGraph, Node, make_node_id


@dataclass
class MemoryConflict:
    id: str
    type: str
    severity: float
    summary: str
    node_ids: list[str]
    node_label: str = ""
    old_value: str = ""
    new_value: str = ""
    source_quotes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "summary": self.summary,
            "node_ids": list(self.node_ids),
            "node_label": self.node_label,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "source_quotes": list(self.source_quotes),
            "metadata": dict(self.metadata),
        }


def list_memory_conflicts(graph: CortexGraph, min_severity: float = 0.0) -> list[MemoryConflict]:
    engine = ContradictionEngine()
    return [
        MemoryConflict(
            id=item.id,
            type=item.type,
            severity=item.severity,
            summary=item.description,
            node_ids=list(item.node_ids),
            node_label=item.node_label,
            old_value=item.old_value,
            new_value=item.new_value,
            source_quotes=list(item.source_quotes or []),
            metadata=dict(item.metadata or {}),
        )
        for item in engine.detect_all(graph, min_severity=min_severity)
    ]


def show_memory_nodes(
    graph: CortexGraph,
    label: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    nodes = graph.find_nodes(label=label, tag=tag)
    nodes.sort(key=lambda node: (-node.confidence, node.label.lower(), node.id))
    return [node.to_dict() for node in nodes[:limit]]


def forget_nodes(
    graph: CortexGraph,
    node_id: str | None = None,
    label: str | None = None,
    tag: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    target_ids: set[str] = set()
    if node_id:
        target_ids.add(node_id)
    if label:
        target_ids.update(graph.find_node_ids_by_label(label))
    if tag:
        target_ids.update(graph.find_node_ids_by_tag(tag))

    existing_ids = sorted(node_id for node_id in target_ids if graph.get_node(node_id) is not None)
    if dry_run:
        return {
            "status": "ok",
            "dry_run": True,
            "node_ids": existing_ids,
            "nodes_removed": len(existing_ids),
        }

    removed = graph.remove_nodes(existing_ids)
    return {
        "status": "ok",
        "dry_run": False,
        "node_ids": existing_ids,
        "nodes_removed": removed,
    }


def set_memory_node(
    graph: CortexGraph,
    label: str,
    tags: list[str],
    brief: str = "",
    description: str = "",
    properties: dict[str, str] | None = None,
    confidence: float = 0.95,
    replace_label: str | None = None,
) -> dict[str, Any]:
    target_ids = graph.find_node_ids_by_label(replace_label or label)
    created = False
    updated = False
    if target_ids:
        node = graph.get_node(target_ids[0])
        assert node is not None
        node.label = label
        node.tags = list(dict.fromkeys(node.tags + tags))
        node.confidence = confidence
        if brief:
            node.brief = brief
        if description:
            node.full_description = description
        if properties:
            node.properties.update(properties)
        updated = True
    else:
        node = Node(
            id=make_node_id(label),
            label=label,
            tags=list(dict.fromkeys(tags)),
            confidence=confidence,
            properties=dict(properties or {}),
            brief=brief,
            full_description=description,
        )
        graph.add_node(node)
        created = True

    return {
        "status": "ok",
        "node_id": node.id,
        "created": created,
        "updated": updated,
    }


def resolve_memory_conflict(graph: CortexGraph, conflict_id: str, action: str) -> dict[str, Any]:
    conflicts = list_memory_conflicts(graph)
    conflict = next((item for item in conflicts if item.id == conflict_id), None)
    if conflict is None:
        return {
            "status": "error",
            "error": "conflict_not_found",
            "conflict_id": conflict_id,
        }

    if action == "ignore":
        return {
            "status": "ok",
            "conflict_id": conflict_id,
            "action": action,
            "nodes_updated": 0,
            "nodes_removed": 0,
        }

    if conflict.type == "negation_conflict" and action in {"accept-new", "keep-old"}:
        node = graph.get_node(conflict.node_ids[0]) if conflict.node_ids else None
        if node is None:
            return {
                "status": "error",
                "error": "node_not_found",
                "conflict_id": conflict_id,
            }
        if action == "accept-new":
            node.tags = ["negations"] + [tag for tag in node.tags if tag == "negations"]
        else:
            node.tags = [tag for tag in node.tags if tag != "negations"]
        return {
            "status": "ok",
            "conflict_id": conflict_id,
            "action": action,
            "nodes_updated": 1,
            "nodes_removed": 0,
        }

    return {
        "status": "error",
        "error": "not_yet_supported",
        "conflict_id": conflict_id,
        "action": action,
    }
