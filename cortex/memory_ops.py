from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cortex.graph.claims import ClaimLedger
from cortex.graph.contradictions import ContradictionEngine
from cortex.graph.graph import CortexGraph, Node, make_node_id
from cortex.versioning.upai.versioning import VersionStore


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


def retract_source(
    graph: CortexGraph,
    source: str,
    dry_run: bool = False,
    prune_orphans: bool = True,
) -> dict[str, Any]:
    working_graph = CortexGraph.from_v5_json(graph.export_v5()) if dry_run else graph
    result = working_graph.retract_source(source=source, prune_orphans=prune_orphans)
    result["dry_run"] = dry_run
    return result


def blame_memory_nodes(
    graph: CortexGraph,
    label: str | None = None,
    node_id: str | None = None,
    store: VersionStore | None = None,
    ledger: ClaimLedger | None = None,
    ref: str = "HEAD",
    source: str = "",
    version_limit: int = 20,
) -> dict[str, Any]:
    target_ids: set[str] = set()
    if node_id:
        target_ids.add(node_id)
    if label:
        target_ids.update(graph.find_node_ids_by_label(label))

    nodes = [graph.get_node(item_id) for item_id in sorted(target_ids)]
    nodes = [node for node in nodes if node is not None]

    results: list[dict[str, Any]] = []
    for node in nodes:
        provenance_sources = sorted(
            {str(item.get("source", "")).strip() for item in node.provenance if str(item.get("source", "")).strip()}
        )
        snapshot_sources = sorted(
            {str(item.get("source", "")).strip() for item in node.snapshots if str(item.get("source", "")).strip()}
        )
        why_present = []
        if provenance_sources:
            why_present.append(f"Current node carries provenance from: {', '.join(provenance_sources)}")
        if snapshot_sources:
            why_present.append(f"Observed in {len(node.snapshots)} snapshot(s) from: {', '.join(snapshot_sources)}")
        if node.status or node.valid_from or node.valid_to:
            status = node.status or "unspecified"
            why_present.append(
                f"Lifecycle claim is {status} with validity {node.valid_from or '?'} -> {node.valid_to or '?'}"
            )

        history = None
        if store is not None:
            history = store.blame_node(
                node_id=node.id,
                label=node.label,
                aliases=list(node.aliases),
                canonical_id=node.canonical_id or node.id,
                ref=ref,
                source=source,
                limit=version_limit,
            )
        claim_lineage = (
            ledger.lineage_for_node(node, limit=version_limit, source=source) if ledger is not None else None
        )

        if source:
            normalized_source = source.strip().lower()
            provenance_sources = [value for value in provenance_sources if value.lower() == normalized_source]
            snapshot_sources = [value for value in snapshot_sources if value.lower() == normalized_source]
            why_present = [
                reason for reason in why_present if normalized_source in reason.lower() or "Lifecycle claim" in reason
            ]

        has_filtered_receipt = bool(provenance_sources or snapshot_sources)
        has_filtered_history = bool(history and history.get("versions_seen"))
        has_filtered_claims = bool(claim_lineage and claim_lineage.get("event_count"))
        if source and not any((has_filtered_receipt, has_filtered_history, has_filtered_claims)):
            continue

        results.append(
            {
                "node": node.to_dict(),
                "provenance_sources": provenance_sources,
                "snapshot_sources": snapshot_sources,
                "why_present": why_present,
                "history": history,
                "claim_lineage": claim_lineage,
            }
        )

    return {
        "status": "ok",
        "nodes": results,
    }


def set_memory_node(
    graph: CortexGraph,
    label: str,
    tags: list[str],
    aliases: list[str] | None = None,
    brief: str = "",
    description: str = "",
    properties: dict[str, str] | None = None,
    confidence: float = 0.95,
    valid_from: str = "",
    valid_to: str = "",
    status: str = "",
    provenance_source: str = "",
    replace_label: str | None = None,
) -> dict[str, Any]:
    target_ids = graph.find_node_ids_by_label(replace_label or label)
    created = False
    updated = False
    aliases = list(dict.fromkeys(aliases or []))
    provenance_entry = {"source": provenance_source, "method": "manual"} if provenance_source else None
    if target_ids:
        node = graph.get_node(target_ids[0])
        assert node is not None
        node.label = label
        node.tags = list(dict.fromkeys(node.tags + tags))
        node.aliases = list(dict.fromkeys(node.aliases + aliases))
        node.confidence = confidence
        if brief:
            node.brief = brief
        if description:
            node.full_description = description
        if properties:
            node.properties.update(properties)
        if valid_from:
            node.valid_from = valid_from
        if valid_to:
            node.valid_to = valid_to
        if status:
            node.status = status
        if provenance_entry and provenance_entry not in node.provenance:
            node.provenance.append(provenance_entry)
        updated = True
    else:
        node = Node(
            id=make_node_id(label),
            label=label,
            tags=list(dict.fromkeys(tags)),
            aliases=aliases,
            confidence=confidence,
            properties=dict(properties or {}),
            brief=brief,
            full_description=description,
            valid_from=valid_from,
            valid_to=valid_to,
            status=status,
            provenance=[provenance_entry] if provenance_entry else [],
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

    if conflict.type == "tag_conflict" and action in {"accept-new", "keep-old"}:
        node = graph.get_node(conflict.node_ids[0]) if conflict.node_ids else None
        if node is None:
            return {
                "status": "error",
                "error": "node_not_found",
                "conflict_id": conflict_id,
            }
        chosen_tag = conflict.new_value if action == "accept-new" else conflict.old_value
        dropped_tag = conflict.old_value if action == "accept-new" else conflict.new_value
        node.tags = [tag for tag in node.tags if tag != dropped_tag]
        if chosen_tag and chosen_tag not in node.tags:
            node.tags.append(chosen_tag)
        return {
            "status": "ok",
            "conflict_id": conflict_id,
            "action": action,
            "nodes_updated": 1,
            "nodes_removed": 0,
        }

    if conflict.type == "temporal_flip" and action in {"accept-new", "keep-old"}:
        node = graph.get_node(conflict.node_ids[0]) if conflict.node_ids else None
        if node is None:
            return {
                "status": "error",
                "error": "node_not_found",
                "conflict_id": conflict_id,
            }
        chosen = conflict.new_value if action == "accept-new" else conflict.old_value
        try:
            node.confidence = float(chosen)
        except (TypeError, ValueError):
            return {
                "status": "error",
                "error": "invalid_confidence",
                "conflict_id": conflict_id,
            }
        return {
            "status": "ok",
            "conflict_id": conflict_id,
            "action": action,
            "nodes_updated": 1,
            "nodes_removed": 0,
        }

    if conflict.type == "source_conflict":
        nodes = [graph.get_node(node_id) for node_id in conflict.node_ids]
        nodes = [node for node in nodes if node is not None]
        if not nodes:
            return {
                "status": "error",
                "error": "node_not_found",
                "conflict_id": conflict_id,
            }

        def _latest_ts(node: Node) -> str:
            return max((snap.get("timestamp", "") for snap in node.snapshots), default="")

        def _earliest_ts(node: Node) -> str:
            return min((snap.get("timestamp", "") for snap in node.snapshots), default="")

        if action == "merge":
            target = max(nodes, key=lambda node: (node.confidence, _latest_ts(node)))
        elif action == "accept-new":
            target = max(nodes, key=_latest_ts)
        elif action == "keep-old":
            target = min(nodes, key=_earliest_ts)
        else:
            target = None

        if target is not None:
            removed_ids = []
            for node in nodes:
                if node.id == target.id:
                    continue
                target.tags = list(dict.fromkeys(target.tags + node.tags))
                target.metrics = list(dict.fromkeys(target.metrics + node.metrics))
                target.timeline = list(dict.fromkeys(target.timeline + node.timeline))
                target.source_quotes = list(dict.fromkeys(target.source_quotes + node.source_quotes))
                target.snapshots = sorted(
                    target.snapshots + node.snapshots,
                    key=lambda snap: snap.get("timestamp", ""),
                )
                if len(node.brief) > len(target.brief):
                    target.brief = node.brief
                if len(node.full_description) > len(target.full_description):
                    target.full_description = node.full_description
                for key, value in node.properties.items():
                    target.properties.setdefault(key, value)
                removed_ids.append(node.id)
            nodes_removed = graph.remove_nodes(removed_ids)
            return {
                "status": "ok",
                "conflict_id": conflict_id,
                "action": action,
                "nodes_updated": 1,
                "nodes_removed": nodes_removed,
                "target_node_id": target.id,
            }

    return {
        "status": "error",
        "error": "not_yet_supported",
        "conflict_id": conflict_id,
        "action": action,
    }
