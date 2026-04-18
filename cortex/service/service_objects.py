from __future__ import annotations

from typing import Any

from cortex.claims import ClaimEvent
from cortex.graph import CortexGraph, Edge, Node, _normalize_label, make_edge_id, make_node_id
from cortex.schemas.memory_v1 import ClaimRecord, MemoryEdgeRecord, MemoryNodeRecord
from cortex.service_common import _load_identity, _now_iso


def _copy_graph(graph: CortexGraph) -> CortexGraph:
    return CortexGraph.from_v5_json(graph.export_v5())


def _dedupe_dict_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        normalized = tuple(sorted((str(key), repr(value)) for key, value in dict(item).items()))
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(dict(item))
    return deduped


def _normalize_external_merge_metadata(source: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(metadata or {})
    if source != "merge:external":
        return normalized
    incoming_graph_hash = str(normalized.get("source_id") or normalized.get("incoming_graph_hash") or "").strip()
    if incoming_graph_hash:
        normalized["source_id"] = incoming_graph_hash
    normalized.pop("incoming_graph_hash", None)
    return normalized


def _record_namespace(service: Any, ref: str) -> str:
    return service._ref_namespace(ref) or service.backend.versions.current_branch()


def _lookup_nodes(
    graph: CortexGraph,
    *,
    node_id: str = "",
    canonical_id: str = "",
    label: str = "",
    limit: int = 10,
) -> list[Node]:
    if node_id:
        node = graph.get_node(node_id)
        return [node] if node is not None else []
    matches = list(graph.nodes.values())
    if canonical_id:
        matches = [node for node in matches if node.canonical_id == canonical_id or node.id == canonical_id]
    if label:
        normalized = _normalize_label(label)
        matches = [
            node
            for node in matches
            if _normalize_label(node.label) == normalized
            or normalized in {_normalize_label(alias) for alias in node.aliases}
        ]
    matches.sort(key=lambda node: (-node.confidence, node.label.lower(), node.id))
    return matches[:limit]


def _resolve_single_node_match(
    graph: CortexGraph,
    *,
    node_id: str = "",
    canonical_id: str = "",
    label: str = "",
) -> tuple[Node | None, str]:
    if node_id:
        node = graph.get_node(node_id)
        return node, "id" if node is not None else ""
    if canonical_id:
        matches = _lookup_nodes(graph, canonical_id=canonical_id, limit=10)
        if len(matches) > 1:
            raise ValueError(f"Multiple nodes match canonical_id '{canonical_id}'.")
        return (matches[0], "canonical_id") if matches else (None, "")
    if label:
        matches = _lookup_nodes(graph, label=label, limit=10)
        if len(matches) > 1:
            raise ValueError(f"Multiple nodes match label '{label}'.")
        return (matches[0], "label") if matches else (None, "")
    return None, ""


def _lookup_edges(
    graph: CortexGraph,
    *,
    edge_id: str = "",
    source_id: str = "",
    target_id: str = "",
    relation: str = "",
    limit: int = 10,
) -> list[Edge]:
    if edge_id:
        edge = graph.get_edge(edge_id)
        return [edge] if edge is not None else []
    matches = list(graph.edges.values())
    if source_id:
        matches = [edge for edge in matches if edge.source_id == source_id]
    if target_id:
        matches = [edge for edge in matches if edge.target_id == target_id]
    if relation:
        matches = [edge for edge in matches if edge.relation == relation]
    matches.sort(key=lambda edge: (-edge.confidence, edge.relation.lower(), edge.id))
    return matches[:limit]


def _resolve_single_edge_match(
    graph: CortexGraph,
    *,
    edge_id: str = "",
    source_id: str = "",
    target_id: str = "",
    relation: str = "",
) -> tuple[Edge | None, str]:
    if edge_id:
        edge = graph.get_edge(edge_id)
        return edge, "id" if edge is not None else ""
    if source_id and target_id and relation:
        matches = _lookup_edges(
            graph,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            limit=10,
        )
        if len(matches) > 1:
            raise ValueError(
                f"Multiple edges match source_id/target_id/relation ('{source_id}', '{target_id}', '{relation}')."
            )
        return (matches[0], "triple") if matches else (None, "")
    return None, ""


def _claim_lineage_empty() -> dict[str, Any]:
    return {
        "event_count": 0,
        "claim_count": 0,
        "assert_count": 0,
        "retract_count": 0,
        "sources": [],
        "claim_ids": [],
        "introduced_at": None,
        "latest_event": None,
        "events": [],
    }


def _claim_lineage_counts(records: list[ClaimRecord]) -> dict[str, Any]:
    claim_ids = sorted({record.claim_id for record in records})
    return {
        "event_count": len(records),
        "claim_count": len(claim_ids),
        "assert_count": sum(1 for record in records if record.op == "assert"),
        "retract_count": sum(1 for record in records if record.op == "retract"),
        "sources": sorted({record.source for record in records if record.source}),
        "claim_ids": claim_ids,
    }


def _claim_lineage_introduced(record: ClaimRecord) -> dict[str, Any]:
    return {
        "timestamp": record.timestamp,
        "source": record.source,
        "method": record.method,
        "claim_id": record.claim_id,
        "version_id": record.version_id,
    }


def _claim_lineage_latest(record: ClaimRecord) -> dict[str, Any]:
    return {
        "timestamp": record.timestamp,
        "op": record.op,
        "source": record.source,
        "method": record.method,
        "claim_id": record.claim_id,
        "version_id": record.version_id,
    }


def _claim_lineage_events(records: list[ClaimRecord]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def _claim_lineage_from_records(records: list[ClaimRecord]) -> dict[str, Any]:
    if not records:
        return _claim_lineage_empty()
    chronological = list(reversed(records))
    return {
        **_claim_lineage_counts(records),
        "introduced_at": _claim_lineage_introduced(chronological[0]),
        "latest_event": _claim_lineage_latest(records[0]),
        "events": _claim_lineage_events(records),
    }


class MemoryObjectServiceMixin:
    def _record_namespace(self, ref: str) -> str:
        return _record_namespace(self, ref)

    def _claim_records(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        source: str = "",
        version_ref: str = "",
        op: str = "",
        limit: int = 50,
        namespace: str | None = None,
    ) -> list[ClaimRecord]:
        records = self.backend.claims.list_events(
            claim_id=claim_id,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
            source=source,
            version_ref=version_ref,
            op=op,
            limit=limit,
        )
        if not namespace:
            return records
        filtered: list[ClaimRecord] = []
        for record in records:
            if record.version_id:
                commit = self.backend.versions.head(ref=record.version_id)
                if commit is None or not self._branch_in_namespace(commit.namespace, namespace):
                    continue
            elif not self._branch_in_namespace(self.backend.versions.current_branch(), namespace):
                continue
            filtered.append(record)
        return filtered

    def _serialize_node(self, node: Node, *, namespace: str) -> dict[str, Any]:
        return MemoryNodeRecord.from_node(node, tenant_id=self.backend.tenant_id, namespace=namespace).to_dict()

    def _serialize_edge(self, edge: Edge, *, namespace: str) -> dict[str, Any]:
        return MemoryEdgeRecord.from_edge(edge, tenant_id=self.backend.tenant_id, namespace=namespace).to_dict()

    def _serialize_claim(self, record: ClaimRecord, *, namespace: str) -> dict[str, Any]:
        payload = record.to_dict()
        payload["tenant_id"] = self.backend.tenant_id
        payload["namespace"] = namespace
        return payload

    def _node_detail_payload(
        self,
        node: Node,
        graph: CortexGraph,
        *,
        ref: str,
        graph_source: str,
        namespace: str | None,
    ) -> dict[str, Any]:
        resolved_namespace = self._record_namespace(ref)
        claims = self._claim_records(
            node_id=node.id,
            canonical_id=node.canonical_id or node.id,
            label=node.label,
            limit=20,
            namespace=namespace,
        )
        return {
            "status": "ok",
            "graph_source": graph_source,
            "ref": ref,
            "node": self._serialize_node(node, namespace=resolved_namespace),
            "connected_edges": [
                self._serialize_edge(edge, namespace=resolved_namespace) for edge in graph.get_edges_for(node.id)
            ],
            "neighbor_ids": sorted({neighbor.id for _, neighbor in graph.get_neighbors(node.id)}),
            "claim_lineage": _claim_lineage_from_records(claims),
        }

    def _edge_detail_payload(
        self,
        edge: Edge,
        graph: CortexGraph,
        *,
        ref: str,
        graph_source: str,
    ) -> dict[str, Any]:
        resolved_namespace = self._record_namespace(ref)
        source_node = graph.get_node(edge.source_id)
        target_node = graph.get_node(edge.target_id)
        return {
            "status": "ok",
            "graph_source": graph_source,
            "ref": ref,
            "edge": self._serialize_edge(edge, namespace=resolved_namespace),
            "source_node": self._serialize_node(source_node, namespace=resolved_namespace) if source_node else None,
            "target_node": self._serialize_node(target_node, namespace=resolved_namespace) if target_node else None,
        }

    def _apply_node_upsert(
        self,
        graph: CortexGraph,
        payload: dict[str, Any],
        *,
        source: str,
        method: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw = dict(payload)
        metadata = _normalize_external_merge_metadata(source, metadata)
        existing, matched_by = _resolve_single_node_match(
            graph,
            node_id=str(raw.get("id", "")).strip(),
            canonical_id=str(raw.get("canonical_id", "")).strip(),
            label=str(raw.get("label", "")).strip(),
        )
        timestamp = _now_iso()
        node_id = existing.id if existing is not None else str(raw.get("id", "")).strip()
        label = str(raw.get("label", "")).strip()
        canonical_id = str(raw.get("canonical_id", "")).strip()
        if existing is None and not node_id:
            node_id = canonical_id or make_node_id(label)
        base = (
            existing.to_dict()
            if existing is not None
            else {"id": node_id, "label": label, "canonical_id": canonical_id or node_id}
        )
        for key, value in raw.items():
            base[key] = value
        base["id"] = node_id
        base["label"] = str(base.get("label", "")).strip()
        if not base["label"]:
            raise ValueError("node.label is required")
        base["canonical_id"] = str(base.get("canonical_id") or (existing.canonical_id if existing else node_id))
        if existing is None and not base.get("first_seen"):
            base["first_seen"] = timestamp
        if "last_seen" not in raw or not raw.get("last_seen"):
            base["last_seen"] = timestamp
        provenance = [dict(item) for item in base.get("provenance", [])]
        provenance_entry = {
            key: value
            for key, value in {"source": source, "method": method, **metadata}.items()
            if value != "" and value is not None and value != [] and value != {}
        }
        if provenance_entry:
            provenance.append(provenance_entry)
        base["provenance"] = _dedupe_dict_items(provenance)
        node = Node.from_dict(base)
        graph.add_node(node)
        return {
            "node": node,
            "created": existing is None,
            "matched_by": matched_by or ("new" if existing is None else "id"),
        }

    def _apply_edge_upsert(
        self,
        graph: CortexGraph,
        payload: dict[str, Any],
        *,
        source: str,
        method: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw = dict(payload)
        metadata = _normalize_external_merge_metadata(source, metadata)
        existing, matched_by = _resolve_single_edge_match(
            graph,
            edge_id=str(raw.get("id", "")).strip(),
            source_id=str(raw.get("source_id", "")).strip(),
            target_id=str(raw.get("target_id", "")).strip(),
            relation=str(raw.get("relation", "")).strip(),
        )
        base = existing.to_dict() if existing is not None else {}
        for key, value in raw.items():
            base[key] = value
        source_id = str(base.get("source_id", "")).strip()
        target_id = str(base.get("target_id", "")).strip()
        relation = str(base.get("relation", "")).strip()
        if not source_id or not target_id or not relation:
            raise ValueError("edge.source_id, edge.target_id, and edge.relation are required")
        if source_id not in graph.nodes or target_id not in graph.nodes:
            raise ValueError("Edge endpoints must exist before upserting an edge.")
        timestamp = _now_iso()
        edge_id = (
            existing.id
            if existing is not None
            else str(base.get("id", "")).strip() or make_edge_id(source_id, target_id, relation)
        )
        base["id"] = edge_id
        base["source_id"] = source_id
        base["target_id"] = target_id
        base["relation"] = relation
        if existing is None and not base.get("first_seen"):
            base["first_seen"] = timestamp
        if "last_seen" not in raw or not raw.get("last_seen"):
            base["last_seen"] = timestamp
        provenance = [dict(item) for item in base.get("provenance", [])]
        provenance_entry = {
            key: value
            for key, value in {"source": source, "method": method, **metadata}.items()
            if value != "" and value is not None and value != [] and value != {}
        }
        if provenance_entry:
            provenance.append(provenance_entry)
        base["provenance"] = _dedupe_dict_items(provenance)
        edge = Edge.from_dict(base)
        graph.add_edge(edge)
        return {
            "edge": edge,
            "created": existing is None,
            "matched_by": matched_by or ("new" if existing is None else "id"),
        }

    def _apply_node_delete(
        self,
        graph: CortexGraph,
        *,
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
    ) -> dict[str, Any]:
        existing, matched_by = _resolve_single_node_match(
            graph,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
        )
        if existing is None:
            raise FileNotFoundError("Node not found")
        removed_node = Node.from_dict(existing.to_dict())
        before_edges = set(graph.edges)
        graph.remove_node(existing.id)
        return {
            "node": removed_node,
            "matched_by": matched_by,
            "removed_edge_ids": sorted(before_edges - set(graph.edges)),
        }

    def _apply_edge_delete(
        self,
        graph: CortexGraph,
        *,
        edge_id: str = "",
        source_id: str = "",
        target_id: str = "",
        relation: str = "",
    ) -> dict[str, Any]:
        existing, matched_by = _resolve_single_edge_match(
            graph,
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
        )
        if existing is None:
            raise FileNotFoundError("Edge not found")
        removed_edge = Edge.from_dict(existing.to_dict())
        graph.remove_edge(existing.id)
        return {
            "edge": removed_edge,
            "matched_by": matched_by,
        }

    def _find_claim_record(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        source: str = "",
        namespace: str | None = None,
    ) -> ClaimRecord:
        records = self._claim_records(
            claim_id=claim_id,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
            source=source,
            limit=50,
            namespace=namespace,
        )
        if not records:
            raise FileNotFoundError("Claim not found")
        return records[0]

    def _commit_object_graph(
        self,
        *,
        current_graph: CortexGraph,
        baseline_graph: CortexGraph | None,
        message: str,
        source: str,
        actor: str,
        approve: bool,
        namespace: str | None,
    ) -> dict[str, Any] | None:
        changed = (
            bool(current_graph.nodes or current_graph.edges)
            if baseline_graph is None
            else baseline_graph.export_v5() != current_graph.export_v5()
        )
        if not changed:
            return None
        current_branch = self.backend.versions.current_branch()
        self._enforce_namespace(namespace, branch=current_branch)
        self._authorize(
            actor=actor,
            action="write",
            namespace=current_branch,
            approve=approve,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        )
        return self.backend.versions.commit(
            current_graph,
            message,
            source=source,
            identity=_load_identity(self.store_dir),
        ).to_dict()

    def _append_assert_claim(
        self,
        *,
        node: Node,
        version_id: str = "",
        source: str,
        method: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = ClaimEvent.from_node(
            node,
            op="assert",
            source=source,
            method=method,
            version_id=version_id,
            message=message,
            metadata=metadata,
        )
        self.backend.claims.append(event)
        return ClaimRecord.from_claim_event(
            event,
            tenant_id=self.backend.tenant_id,
            namespace=self.backend.versions.current_branch(),
        ).to_dict()

    def _append_retract_claim(
        self,
        *,
        record: ClaimRecord,
        version_id: str = "",
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = ClaimEvent.decision_from_event(
            ClaimEvent.from_dict(record.to_dict()),
            op="retract",
            version_id=version_id,
            message=message,
            metadata=metadata,
        )
        self.backend.claims.append(event)
        return ClaimRecord.from_claim_event(
            event,
            tenant_id=self.backend.tenant_id,
            namespace=self.backend.versions.current_branch(),
        ).to_dict()

    def lookup_nodes(
        self,
        *,
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        limit: int = 10,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(ref=ref, namespace=namespace)
        resolved_namespace = self._record_namespace(ref)
        nodes = _lookup_nodes(
            current_graph,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
            limit=limit,
        )
        return {
            "status": "ok",
            "graph_source": graph_source,
            "ref": ref,
            "criteria": {
                "node_id": node_id,
                "canonical_id": canonical_id,
                "label": label,
                "limit": limit,
            },
            "nodes": [self._serialize_node(node, namespace=resolved_namespace) for node in nodes],
            "count": len(nodes),
        }

    def get_node(
        self,
        *,
        node_id: str,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(ref=ref, namespace=namespace)
        node = current_graph.get_node(node_id)
        if node is None:
            raise FileNotFoundError(f"Node not found: {node_id}")
        return self._node_detail_payload(
            node,
            current_graph,
            ref=ref,
            graph_source=graph_source,
            namespace=namespace,
        )

    def upsert_node(
        self,
        *,
        node: dict[str, Any],
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
        record_claim: bool = True,
        claim_source: str = "",
        claim_method: str = "nodes.upsert",
        claim_metadata: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, baseline_graph, current_branch, _ = self._graph_for_write(ref=ref, namespace=namespace)
        result = self._apply_node_upsert(
            current_graph,
            node,
            source=source,
            method="nodes.upsert",
            metadata={"actor": actor},
        )
        commit_message = message or f"Upsert node '{result['node'].label}'"
        commit = self._commit_object_graph(
            current_graph=current_graph,
            baseline_graph=baseline_graph,
            message=commit_message,
            source=source,
            actor=actor,
            approve=approve,
            namespace=namespace,
        )
        claim = None
        if record_claim:
            claim = self._append_assert_claim(
                node=result["node"],
                version_id=commit["version_id"] if commit else "",
                source=claim_source or source,
                method=claim_method,
                message=commit_message,
                metadata={"operation": "nodes.upsert", **dict(claim_metadata or {})},
            )
        return {
            "status": "ok",
            "branch": current_branch,
            "ref": ref,
            "created": result["created"],
            "matched_by": result["matched_by"],
            "node": self._serialize_node(result["node"], namespace=current_branch),
            "commit": commit,
            "claim": claim,
        }

    def delete_node(
        self,
        *,
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
        record_claim: bool = True,
        claim_source: str = "",
        claim_method: str = "nodes.delete",
        claim_metadata: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, baseline_graph, current_branch, _ = self._graph_for_write(ref=ref, namespace=namespace)
        result = self._apply_node_delete(
            current_graph,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
        )
        commit_message = message or f"Delete node '{result['node'].label}'"
        commit = self._commit_object_graph(
            current_graph=current_graph,
            baseline_graph=baseline_graph,
            message=commit_message,
            source=source,
            actor=actor,
            approve=approve,
            namespace=namespace,
        )
        claim = None
        if record_claim:
            claim = ClaimRecord.from_claim_event(
                ClaimEvent.from_node(
                    result["node"],
                    op="retract",
                    source=claim_source or source,
                    method=claim_method,
                    version_id=commit["version_id"] if commit else "",
                    message=commit_message,
                    metadata={"operation": "nodes.delete", **dict(claim_metadata or {})},
                ),
                tenant_id=self.backend.tenant_id,
                namespace=current_branch,
            )
            self.backend.claims.append(ClaimEvent.from_dict(claim.to_dict()))
            claim = claim.to_dict()
        return {
            "status": "ok",
            "branch": current_branch,
            "ref": ref,
            "matched_by": result["matched_by"],
            "node": self._serialize_node(result["node"], namespace=current_branch),
            "removed_edge_ids": result["removed_edge_ids"],
            "commit": commit,
            "claim": claim,
        }

    def lookup_edges(
        self,
        *,
        edge_id: str = "",
        source_id: str = "",
        target_id: str = "",
        relation: str = "",
        ref: str = "HEAD",
        limit: int = 10,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(ref=ref, namespace=namespace)
        resolved_namespace = self._record_namespace(ref)
        edges = _lookup_edges(
            current_graph,
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            limit=limit,
        )
        return {
            "status": "ok",
            "graph_source": graph_source,
            "ref": ref,
            "criteria": {
                "edge_id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "limit": limit,
            },
            "edges": [self._serialize_edge(edge, namespace=resolved_namespace) for edge in edges],
            "count": len(edges),
        }

    def get_edge(
        self,
        *,
        edge_id: str,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(ref=ref, namespace=namespace)
        edge = current_graph.get_edge(edge_id)
        if edge is None:
            raise FileNotFoundError(f"Edge not found: {edge_id}")
        return self._edge_detail_payload(edge, current_graph, ref=ref, graph_source=graph_source)

    def upsert_edge(
        self,
        *,
        edge: dict[str, Any],
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, baseline_graph, current_branch, _ = self._graph_for_write(ref=ref, namespace=namespace)
        result = self._apply_edge_upsert(
            current_graph,
            edge,
            source=source,
            method="edges.upsert",
            metadata={"actor": actor},
        )
        commit_message = message or f"Upsert edge '{result['edge'].relation}'"
        commit = self._commit_object_graph(
            current_graph=current_graph,
            baseline_graph=baseline_graph,
            message=commit_message,
            source=source,
            actor=actor,
            approve=approve,
            namespace=namespace,
        )
        return {
            "status": "ok",
            "branch": current_branch,
            "ref": ref,
            "created": result["created"],
            "matched_by": result["matched_by"],
            "edge": self._serialize_edge(result["edge"], namespace=current_branch),
            "commit": commit,
        }

    def delete_edge(
        self,
        *,
        edge_id: str = "",
        source_id: str = "",
        target_id: str = "",
        relation: str = "",
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, baseline_graph, current_branch, _ = self._graph_for_write(ref=ref, namespace=namespace)
        result = self._apply_edge_delete(
            current_graph,
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
        )
        commit_message = message or f"Delete edge '{result['edge'].relation}'"
        commit = self._commit_object_graph(
            current_graph=current_graph,
            baseline_graph=baseline_graph,
            message=commit_message,
            source=source,
            actor=actor,
            approve=approve,
            namespace=namespace,
        )
        return {
            "status": "ok",
            "branch": current_branch,
            "ref": ref,
            "matched_by": result["matched_by"],
            "edge": self._serialize_edge(result["edge"], namespace=current_branch),
            "commit": commit,
        }

    def list_claims(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        source: str = "",
        ref: str = "",
        version_ref: str = "",
        op: str = "",
        limit: int = 50,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        if ref:
            self._enforce_namespace(namespace, ref=ref)
            resolved = self.backend.versions.resolve_ref(ref)
            if resolved is None:
                raise ValueError(f"Unknown ref: {ref}")
            version_ref = resolved
        records = self._claim_records(
            claim_id=claim_id,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
            source=source,
            version_ref=version_ref,
            op=op,
            limit=limit,
            namespace=namespace,
        )
        resolved_namespace = self.backend.versions.current_branch()
        return {
            "status": "ok",
            "claims": [self._serialize_claim(record, namespace=resolved_namespace) for record in records],
            "count": len(records),
        }

    def assert_claim(
        self,
        *,
        node: dict[str, Any] | None = None,
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        materialize: bool = True,
        message: str = "",
        source: str = "api.object",
        method: str = "claims.assert",
        actor: str = "manual",
        approve: bool = False,
        metadata: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, baseline_graph, current_branch, _ = self._graph_for_write(ref=ref, namespace=namespace)
        claim_node: Node | None = None
        node_result: dict[str, Any] | None = None
        if node is not None:
            if materialize:
                node_result = self._apply_node_upsert(
                    current_graph,
                    node,
                    source=source,
                    method=method,
                    metadata=metadata,
                )
                claim_node = node_result["node"]
            else:
                temp_graph = _copy_graph(current_graph)
                claim_node = self._apply_node_upsert(
                    temp_graph,
                    node,
                    source=source,
                    method=method,
                    metadata=metadata,
                )["node"]
        else:
            claim_node, _ = _resolve_single_node_match(
                current_graph,
                node_id=node_id,
                canonical_id=canonical_id,
                label=label,
            )
            if claim_node is None:
                raise FileNotFoundError("Node not found for claim assertion")
        commit_message = message or f"Assert claim for '{claim_node.label}'"
        commit = None
        if materialize:
            commit = self._commit_object_graph(
                current_graph=current_graph,
                baseline_graph=baseline_graph,
                message=commit_message,
                source=source,
                actor=actor,
                approve=approve,
                namespace=namespace,
            )
        claim = self._append_assert_claim(
            node=claim_node,
            version_id=commit["version_id"] if commit else "",
            source=source,
            method=method,
            message=commit_message,
            metadata=metadata,
        )
        return {
            "status": "ok",
            "branch": current_branch,
            "ref": ref,
            "materialized": materialize,
            "node": self._serialize_node(claim_node, namespace=current_branch),
            "node_change": {
                "created": node_result["created"],
                "matched_by": node_result["matched_by"],
            }
            if node_result is not None
            else None,
            "claim": claim,
            "commit": commit,
        }

    def retract_claim(
        self,
        *,
        claim_id: str = "",
        node_id: str = "",
        canonical_id: str = "",
        label: str = "",
        ref: str = "HEAD",
        materialize: bool = True,
        message: str = "",
        actor: str = "manual",
        approve: bool = False,
        metadata: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, baseline_graph, current_branch, _ = self._graph_for_write(ref=ref, namespace=namespace)
        record = self._find_claim_record(
            claim_id=claim_id,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
            namespace=namespace,
        )
        removed_node: dict[str, Any] | None = None
        if materialize:
            try:
                removed_node = self._apply_node_delete(
                    current_graph,
                    node_id=record.node_id,
                    canonical_id=record.canonical_id,
                    label=record.label,
                )
            except FileNotFoundError:
                removed_node = None
        commit_message = message or f"Retract claim '{record.claim_id}'"
        commit = None
        if materialize:
            commit = self._commit_object_graph(
                current_graph=current_graph,
                baseline_graph=baseline_graph,
                message=commit_message,
                source="api.object",
                actor=actor,
                approve=approve,
                namespace=namespace,
            )
        claim = self._append_retract_claim(
            record=record,
            version_id=commit["version_id"] if commit else "",
            message=commit_message,
            metadata=metadata,
        )
        return {
            "status": "ok",
            "branch": current_branch,
            "ref": ref,
            "materialized": materialize,
            "claim": claim,
            "removed_node": self._serialize_node(removed_node["node"], namespace=current_branch)
            if removed_node
            else None,
            "commit": commit,
        }

    def memory_batch(
        self,
        *,
        operations: list[dict[str, Any]],
        ref: str = "HEAD",
        message: str = "",
        source: str = "api.object",
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, baseline_graph, current_branch, _ = self._graph_for_write(ref=ref, namespace=namespace)
        operation_results: list[dict[str, Any]] = []
        pending_claims: list[dict[str, Any]] = []
        for index, operation in enumerate(operations):
            op_name = str(operation.get("op") or operation.get("type") or "").strip()
            if not op_name:
                raise ValueError(f"Operation {index} is missing 'op'.")
            if op_name == "upsert_node":
                result = self._apply_node_upsert(
                    current_graph,
                    dict(operation.get("node") or {}),
                    source=str(operation.get("source") or source),
                    method="nodes.upsert",
                    metadata=dict(operation.get("metadata") or {"actor": actor}),
                )
                operation_results.append(
                    {
                        "op": op_name,
                        "created": result["created"],
                        "matched_by": result["matched_by"],
                        "node": self._serialize_node(result["node"], namespace=current_branch),
                    }
                )
                if bool(operation.get("record_claim", True)):
                    pending_claims.append(
                        {
                            "kind": "assert",
                            "node": result["node"],
                            "source": str(operation.get("claim_source") or operation.get("source") or source),
                            "method": str(operation.get("claim_method") or "nodes.upsert"),
                            "metadata": {"operation": op_name, **dict(operation.get("claim_metadata") or {})},
                        }
                    )
            elif op_name == "delete_node":
                result = self._apply_node_delete(
                    current_graph,
                    node_id=str(operation.get("node_id", "")),
                    canonical_id=str(operation.get("canonical_id", "")),
                    label=str(operation.get("label", "")),
                )
                operation_results.append(
                    {
                        "op": op_name,
                        "matched_by": result["matched_by"],
                        "node": self._serialize_node(result["node"], namespace=current_branch),
                        "removed_edge_ids": result["removed_edge_ids"],
                    }
                )
                if bool(operation.get("record_claim", True)):
                    pending_claims.append(
                        {
                            "kind": "node_retract",
                            "node": result["node"],
                            "source": str(operation.get("claim_source") or operation.get("source") or source),
                            "method": str(operation.get("claim_method") or "nodes.delete"),
                            "metadata": {"operation": op_name, **dict(operation.get("claim_metadata") or {})},
                        }
                    )
            elif op_name == "upsert_edge":
                result = self._apply_edge_upsert(
                    current_graph,
                    dict(operation.get("edge") or {}),
                    source=str(operation.get("source") or source),
                    method="edges.upsert",
                    metadata=dict(operation.get("metadata") or {"actor": actor}),
                )
                operation_results.append(
                    {
                        "op": op_name,
                        "created": result["created"],
                        "matched_by": result["matched_by"],
                        "edge": self._serialize_edge(result["edge"], namespace=current_branch),
                    }
                )
            elif op_name == "delete_edge":
                result = self._apply_edge_delete(
                    current_graph,
                    edge_id=str(operation.get("edge_id", "")),
                    source_id=str(operation.get("source_id", "")),
                    target_id=str(operation.get("target_id", "")),
                    relation=str(operation.get("relation", "")),
                )
                operation_results.append(
                    {
                        "op": op_name,
                        "matched_by": result["matched_by"],
                        "edge": self._serialize_edge(result["edge"], namespace=current_branch),
                    }
                )
            elif op_name == "assert_claim":
                node_payload = operation.get("node")
                materialize = bool(operation.get("materialize", True))
                node_change = None
                if node_payload is not None:
                    if materialize:
                        node_change = self._apply_node_upsert(
                            current_graph,
                            dict(node_payload),
                            source=str(operation.get("source") or source),
                            method=str(operation.get("method") or "claims.assert"),
                            metadata=dict(operation.get("metadata") or {}),
                        )
                        claim_node = node_change["node"]
                    else:
                        claim_node = self._apply_node_upsert(
                            _copy_graph(current_graph),
                            dict(node_payload),
                            source=str(operation.get("source") or source),
                            method=str(operation.get("method") or "claims.assert"),
                            metadata=dict(operation.get("metadata") or {}),
                        )["node"]
                else:
                    claim_node, _ = _resolve_single_node_match(
                        current_graph,
                        node_id=str(operation.get("node_id", "")),
                        canonical_id=str(operation.get("canonical_id", "")),
                        label=str(operation.get("label", "")),
                    )
                    if claim_node is None:
                        raise FileNotFoundError("Node not found for claim assertion")
                pending_claims.append(
                    {
                        "kind": "assert",
                        "node": claim_node,
                        "source": str(operation.get("source") or source),
                        "method": str(operation.get("method") or "claims.assert"),
                        "metadata": dict(operation.get("metadata") or {}),
                    }
                )
                operation_results.append(
                    {
                        "op": op_name,
                        "materialized": materialize,
                        "node": self._serialize_node(claim_node, namespace=current_branch),
                        "node_change": {
                            "created": node_change["created"],
                            "matched_by": node_change["matched_by"],
                        }
                        if node_change is not None
                        else None,
                    }
                )
            elif op_name == "retract_claim":
                materialize = bool(operation.get("materialize", True))
                record = self._find_claim_record(
                    claim_id=str(operation.get("claim_id", "")),
                    node_id=str(operation.get("node_id", "")),
                    canonical_id=str(operation.get("canonical_id", "")),
                    label=str(operation.get("label", "")),
                    namespace=namespace,
                )
                removed_node = None
                if materialize:
                    try:
                        removed_node = self._apply_node_delete(
                            current_graph,
                            node_id=record.node_id,
                            canonical_id=record.canonical_id,
                            label=record.label,
                        )
                    except FileNotFoundError:
                        removed_node = None
                pending_claims.append(
                    {
                        "kind": "retract_record",
                        "record": record,
                        "metadata": dict(operation.get("metadata") or {}),
                    }
                )
                operation_results.append(
                    {
                        "op": op_name,
                        "materialized": materialize,
                        "claim_id": record.claim_id,
                        "removed_node": self._serialize_node(removed_node["node"], namespace=current_branch)
                        if removed_node
                        else None,
                    }
                )
            else:
                raise ValueError(f"Unsupported memory batch operation: {op_name}")

        commit_message = message or f"Apply {len(operation_results)} memory object operation(s)"
        commit = self._commit_object_graph(
            current_graph=current_graph,
            baseline_graph=baseline_graph,
            message=commit_message,
            source=source,
            actor=actor,
            approve=approve,
            namespace=namespace,
        )
        claim_results: list[dict[str, Any]] = []
        for pending in pending_claims:
            if pending["kind"] == "assert":
                claim_results.append(
                    self._append_assert_claim(
                        node=pending["node"],
                        version_id=commit["version_id"] if commit else "",
                        source=pending["source"],
                        method=pending["method"],
                        message=commit_message,
                        metadata=pending["metadata"],
                    )
                )
            elif pending["kind"] == "node_retract":
                record = ClaimRecord.from_claim_event(
                    ClaimEvent.from_node(
                        pending["node"],
                        op="retract",
                        source=pending["source"],
                        method=pending["method"],
                        version_id=commit["version_id"] if commit else "",
                        message=commit_message,
                        metadata=pending["metadata"],
                    ),
                    tenant_id=self.backend.tenant_id,
                    namespace=current_branch,
                )
                self.backend.claims.append(ClaimEvent.from_dict(record.to_dict()))
                claim_results.append(record.to_dict())
            elif pending["kind"] == "retract_record":
                claim_results.append(
                    self._append_retract_claim(
                        record=pending["record"],
                        version_id=commit["version_id"] if commit else "",
                        message=commit_message,
                        metadata=pending["metadata"],
                    )
                )
        return {
            "status": "ok",
            "branch": current_branch,
            "ref": ref,
            "operation_count": len(operation_results),
            "operations": operation_results,
            "claims": claim_results,
            "commit": commit,
            "materialized": commit is not None,
        }


__all__ = ["MemoryObjectServiceMixin"]
