from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.claims import ClaimEvent
from cortex.compat import upgrade_v4_to_v5
from cortex.embeddings import get_embedding_provider, hybrid_search_documents
from cortex.graph import CortexGraph, Edge, Node, _normalize_label, make_edge_id, make_node_id
from cortex.memory_ops import blame_memory_nodes, list_memory_conflicts, resolve_memory_conflict
from cortex.merge import (
    clear_merge_state,
    load_merge_state,
    load_merge_worktree,
    merge_refs,
    resolve_merge_conflict,
    save_merge_state,
)
from cortex.minds import list_minds, mind_status
from cortex.observability import CortexObservability
from cortex.openapi import build_openapi_spec
from cortex.packs import (
    ask_pack,
    compile_pack,
    export_pack_bundle,
    import_pack_bundle,
    lint_pack,
    list_packs,
    mount_pack,
    pack_artifacts,
    pack_claims,
    pack_concepts,
    pack_lint_report,
    pack_mounts,
    pack_sources,
    pack_status,
    pack_unknowns,
    query_pack,
    render_pack_context,
)
from cortex.portable_runtime import (
    audit_portability,
    render_portability_context,
    scan_portability,
    status_portability,
)
from cortex.query import QueryEngine, parse_nl_query
from cortex.query_lang import ParseError, execute_query
from cortex.release import build_release_metadata
from cortex.review import parse_failure_policies, review_graphs
from cortex.schemas.memory_v1 import ClaimRecord, MemoryEdgeRecord, MemoryNodeRecord
from cortex.storage import get_storage_backend
from cortex.storage.base import StorageBackend
from cortex.upai.identity import UPAIIdentity


def _backend_name(backend: StorageBackend) -> str:
    module_name = type(backend).__module__
    if module_name.endswith(".sqlite"):
        return "sqlite"
    return "filesystem"


def _coerce_graph(payload: dict[str, Any]) -> CortexGraph:
    version = str(payload.get("schema_version", ""))
    if version.startswith("5") or version.startswith("6"):
        return CortexGraph.from_v5_json(payload)
    return upgrade_v4_to_v5(payload)


def _load_identity(store_dir: Path) -> UPAIIdentity | None:
    identity_path = store_dir / "identity.json"
    if not identity_path.exists():
        return None
    return UPAIIdentity.load(store_dir)


def _node_payload(node: Any) -> dict[str, Any]:
    if hasattr(node, "to_dict"):
        return node.to_dict()
    return dict(node)


def _merge_payload(
    *,
    current_ref: str,
    current_branch: str,
    other_ref: str,
    result: Any,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "current_ref": current_ref,
        "current_branch": current_branch,
        "merged_ref": other_ref,
        "base_version": result.base_version,
        "current_version": result.current_version,
        "other_version": result.other_version,
        "summary": result.summary,
        "conflicts": [conflict.to_dict() for conflict in result.conflicts],
        "graph": result.merged.export_v5(),
        "ok": result.ok,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _record_namespace(service: "MemoryService", ref: str) -> str:
    return service._ref_namespace(ref) or service.backend.versions.current_branch()


def _safe_head_ref(service: "MemoryService") -> str:
    try:
        return service.backend.versions.resolve_ref("HEAD")
    except (FileNotFoundError, ValueError):
        return ""


def _safe_index_status(service: "MemoryService") -> dict[str, Any]:
    try:
        return service.backend.indexing.status(ref="HEAD")
    except (FileNotFoundError, ValueError):
        provider = get_embedding_provider()
        return {
            "status": "missing",
            "backend": _backend_name(service.backend),
            "persistent": _backend_name(service.backend) == "sqlite",
            "supported": provider.enabled,
            "ref": "HEAD",
            "resolved_ref": "",
            "last_indexed_commit": None,
            "doc_count": 0,
            "stale": False,
            "updated_at": None,
            "lag_commits": 0,
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
        }


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


def _claim_lineage_from_records(records: list[ClaimRecord]) -> dict[str, Any]:
    if not records:
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
    chronological = list(reversed(records))
    claim_ids = sorted({record.claim_id for record in records})
    sources = sorted({record.source for record in records if record.source})
    assert_count = sum(1 for record in records if record.op == "assert")
    retract_count = sum(1 for record in records if record.op == "retract")
    introduced = chronological[0]
    latest = records[0]
    return {
        "event_count": len(records),
        "claim_count": len(claim_ids),
        "assert_count": assert_count,
        "retract_count": retract_count,
        "sources": sources,
        "claim_ids": claim_ids,
        "introduced_at": {
            "timestamp": introduced.timestamp,
            "source": introduced.source,
            "method": introduced.method,
            "claim_id": introduced.claim_id,
            "version_id": introduced.version_id,
        },
        "latest_event": {
            "timestamp": latest.timestamp,
            "op": latest.op,
            "source": latest.source,
            "method": latest.method,
            "claim_id": latest.claim_id,
            "version_id": latest.version_id,
        },
        "events": [record.to_dict() for record in records],
    }


@dataclass(slots=True)
class MemoryService:
    store_dir: Path
    backend: StorageBackend
    observability: CortexObservability
    context_file: Path | None = None

    def __init__(
        self,
        store_dir: str | Path = ".cortex",
        *,
        context_file: str | Path | None = None,
        backend: StorageBackend | None = None,
        observability: CortexObservability | None = None,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.context_file = Path(context_file).resolve() if context_file else None
        self.backend = backend or get_storage_backend(self.store_dir)
        self.observability = observability or CortexObservability(self.store_dir)

    def _default_graph_ref(self) -> str:
        return "HEAD"

    def _branch_in_namespace(self, branch: str, namespace: str) -> bool:
        return branch == namespace or branch.startswith(f"{namespace}/")

    def _ref_namespace(self, ref: str) -> str | None:
        if ref == "HEAD":
            return self.backend.versions.current_branch()
        if ref.startswith("refs/heads/"):
            return ref[len("refs/heads/") :]
        for branch in self.backend.versions.list_branches():
            if branch.name == ref:
                return branch.name
        head = self.backend.versions.head(ref=ref)
        return head.namespace if head is not None else None

    def _enforce_namespace(self, namespace: str | None, *, ref: str | None = None, branch: str | None = None) -> None:
        if not namespace:
            return
        if branch is not None and not self._branch_in_namespace(branch, namespace):
            raise PermissionError(f"Branch '{branch}' is outside namespace '{namespace}'.")
        if ref is not None:
            resolved_namespace = self._ref_namespace(ref)
            if resolved_namespace is None:
                raise ValueError(f"Unknown ref: {ref}")
            if not self._branch_in_namespace(resolved_namespace, namespace):
                raise PermissionError(
                    f"Ref '{ref}' resolves to namespace '{resolved_namespace}', outside '{namespace}'."
                )

    def _graph_from_request(
        self,
        *,
        graph: dict[str, Any] | None = None,
        ref: str | None = None,
        namespace: str | None = None,
    ) -> tuple[CortexGraph, str]:
        if graph is not None:
            return _coerce_graph(graph), "payload"
        version_ref = ref or self._default_graph_ref()
        self._enforce_namespace(namespace, ref=version_ref)
        version_id = self.backend.versions.resolve_ref(version_ref)
        if version_id is None:
            raise ValueError(f"Unknown ref: {version_ref}")
        return self.backend.versions.checkout(version_id), version_id

    def _authorize(
        self,
        *,
        actor: str,
        action: str,
        namespace: str,
        approve: bool = False,
        current_graph: CortexGraph | None = None,
        baseline_graph: CortexGraph | None = None,
    ) -> None:
        decision = self.backend.governance.authorize(
            actor,
            action,
            namespace,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        )
        if not decision.allowed:
            reasons = "; ".join(decision.reasons) or f"actor '{actor}' cannot {action} namespace '{namespace}'"
            raise PermissionError(reasons)
        if decision.require_approval and not approve:
            reasons = "; ".join(decision.reasons) or "approval required"
            raise PermissionError(f"Approval required: {reasons}")

    def _pending_merge_payload(self) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            return {
                "status": "ok",
                "pending": False,
                "conflicts": [],
            }
        payload = {
            "status": "ok",
            "pending": True,
            "current_branch": state["current_branch"],
            "other_ref": state["other_ref"],
            "base_version": state.get("base_version"),
            "current_version": state.get("current_version"),
            "other_version": state.get("other_version"),
            "summary": state.get("summary", {}),
            "conflicts": state.get("conflicts", []),
            "updated_at": state.get("updated_at", ""),
        }
        try:
            payload["graph"] = load_merge_worktree(self.store_dir).export_v5()
        except FileNotFoundError:
            pass
        return payload

    def health(self) -> dict[str, Any]:
        index_status = _safe_index_status(self)
        return {
            "status": "ok",
            "backend": _backend_name(self.backend),
            "store_dir": str(self.store_dir.resolve()),
            "current_branch": self.backend.versions.current_branch(),
            "head": _safe_head_ref(self),
            "index": index_status,
            "release": self.release(),
        }

    def openapi(self, *, server_url: str | None = None) -> dict[str, Any]:
        return build_openapi_spec(server_url=server_url)

    def release(self) -> dict[str, Any]:
        return build_release_metadata(self.openapi())

    def meta(self) -> dict[str, Any]:
        provider = get_embedding_provider()
        return {
            "status": "ok",
            "store_dir": str(self.store_dir.resolve()),
            "context_file": str(self.context_file) if self.context_file else "",
            "backend": _backend_name(self.backend),
            "current_branch": self.backend.versions.current_branch(),
            "head": _safe_head_ref(self),
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
            "log_path": str(self.observability.log_path),
            "index": _safe_index_status(self),
            "release": self.release(),
        }

    def portability_context(
        self,
        *,
        target: str,
        project_dir: str = "",
        smart: bool | None = None,
        policy: str | None = None,
        max_chars: int = 1500,
    ) -> dict[str, Any]:
        project_path = Path(project_dir).resolve() if project_dir else None
        payload = render_portability_context(
            store_dir=self.store_dir,
            target=target,
            project_dir=project_path,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
        )
        payload["release"] = self.release()
        return payload

    def portability_scan(
        self,
        *,
        project_dir: str = "",
        search_roots: list[str] | None = None,
        metadata_only: bool = False,
    ) -> dict[str, Any]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = scan_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
            extra_roots=[Path(root).resolve() for root in (search_roots or [])],
            metadata_only=metadata_only,
        )
        payload["release"] = self.release()
        return payload

    def portability_status(
        self,
        *,
        project_dir: str = "",
    ) -> dict[str, Any]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = status_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
        )
        payload["release"] = self.release()
        return payload

    def portability_audit(
        self,
        *,
        project_dir: str = "",
    ) -> dict[str, Any]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = audit_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
        )
        payload["release"] = self.release()
        return payload

    def mind_list(self) -> dict[str, Any]:
        payload = list_minds(self.store_dir)
        payload["release"] = self.release()
        return payload

    def mind_status(self, *, name: str) -> dict[str, Any]:
        payload = mind_status(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_list(self) -> dict[str, Any]:
        payload = list_packs(self.store_dir)
        payload["release"] = self.release()
        return payload

    def pack_status(self, *, name: str) -> dict[str, Any]:
        payload = pack_status(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_sources(self, *, name: str) -> dict[str, Any]:
        payload = pack_sources(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_concepts(self, *, name: str) -> dict[str, Any]:
        payload = pack_concepts(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_claims(self, *, name: str) -> dict[str, Any]:
        payload = pack_claims(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_unknowns(self, *, name: str) -> dict[str, Any]:
        payload = pack_unknowns(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_artifacts(self, *, name: str) -> dict[str, Any]:
        payload = pack_artifacts(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_lint_report(self, *, name: str) -> dict[str, Any]:
        payload = pack_lint_report(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_mounts(self, *, name: str) -> dict[str, Any]:
        payload = pack_mounts(self.store_dir, name)
        payload["release"] = self.release()
        return payload

    def pack_compile(
        self,
        *,
        name: str,
        incremental: bool = True,
        suggest_questions: bool = True,
        max_summary_chars: int = 1200,
    ) -> dict[str, Any]:
        payload = compile_pack(
            self.store_dir,
            name,
            incremental=incremental,
            suggest_questions=suggest_questions,
            max_summary_chars=max_summary_chars,
        )
        payload["release"] = self.release()
        return payload

    def pack_query(
        self,
        *,
        name: str,
        query: str,
        limit: int = 8,
        mode: str = "hybrid",
    ) -> dict[str, Any]:
        payload = query_pack(
            self.store_dir,
            name,
            query,
            limit=limit,
            mode=mode,
        )
        payload["release"] = self.release()
        return payload

    def pack_ask(
        self,
        *,
        name: str,
        question: str,
        output: str = "note",
        limit: int = 8,
        write_back: bool = True,
    ) -> dict[str, Any]:
        payload = ask_pack(
            self.store_dir,
            name,
            question,
            output=output,
            limit=limit,
            write_back=write_back,
        )
        payload["release"] = self.release()
        return payload

    def pack_lint(
        self,
        *,
        name: str,
        stale_days: int = 30,
        duplicate_threshold: float = 0.88,
        weak_claim_confidence: float = 0.65,
        thin_article_chars: int = 220,
    ) -> dict[str, Any]:
        payload = lint_pack(
            self.store_dir,
            name,
            stale_days=stale_days,
            duplicate_threshold=duplicate_threshold,
            weak_claim_confidence=weak_claim_confidence,
            thin_article_chars=thin_article_chars,
        )
        payload["release"] = self.release()
        return payload

    def pack_export(
        self,
        *,
        name: str,
        output: str,
        verify: bool = True,
    ) -> dict[str, Any]:
        payload = export_pack_bundle(
            self.store_dir,
            name,
            output,
            verify=verify,
        )
        payload["release"] = self.release()
        return payload

    def pack_import(
        self,
        *,
        archive: str,
        as_name: str = "",
    ) -> dict[str, Any]:
        payload = import_pack_bundle(
            archive,
            self.store_dir,
            as_name=as_name,
        )
        payload["release"] = self.release()
        return payload

    def pack_mount(
        self,
        *,
        name: str,
        targets: list[str],
        project_dir: str = "",
        smart: bool = True,
        policy: str = "technical",
        max_chars: int = 1500,
        openclaw_store_dir: str = "",
    ) -> dict[str, Any]:
        payload = mount_pack(
            self.store_dir,
            name,
            targets=targets,
            project_dir=project_dir,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
            openclaw_store_dir=openclaw_store_dir,
        )
        payload["release"] = self.release()
        return payload

    def pack_context(
        self,
        *,
        name: str,
        target: str,
        project_dir: str = "",
        smart: bool = True,
        policy: str = "technical",
        max_chars: int = 1500,
    ) -> dict[str, Any]:
        payload = render_pack_context(
            self.store_dir,
            name,
            target=target,
            project_dir=project_dir,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
        )
        payload["release"] = self.release()
        return payload

    def channel_prepare_turn(
        self,
        *,
        message: dict[str, Any],
        target: str | None = None,
        smart: bool = True,
        max_chars: int = 1500,
        project_dir: str = "",
    ) -> dict[str, Any]:
        from cortex.channel_runtime import (
            ChannelContextBridge,
            channel_message_from_dict,
            channel_turn_to_dict,
        )

        channel_message = channel_message_from_dict(message)
        if project_dir and not channel_message.project_dir:
            channel_message.project_dir = str(Path(project_dir).resolve())
        bridge = ChannelContextBridge(self, default_project_dir=Path(project_dir).resolve() if project_dir else None)
        turn = bridge.prepare_turn(
            channel_message,
            target=target,
            smart=smart,
            max_chars=max_chars,
        )
        payload = {"status": "ok", "turn": channel_turn_to_dict(turn)}
        payload["release"] = self.release()
        return payload

    def channel_seed_turn_memory(
        self,
        *,
        turn: dict[str, Any],
        ref: str = "HEAD",
        source: str = "channel.runtime",
        approve: bool = False,
    ) -> dict[str, Any]:
        from cortex.channel_runtime import ChannelContextBridge, channel_turn_from_dict

        bridge = ChannelContextBridge(self)
        payload = bridge.seed_turn_memory(
            channel_turn_from_dict(turn),
            ref=ref,
            source=source,
            approve=approve,
        )
        payload["release"] = self.release()
        return payload

    def metrics(self, *, namespace: str | None = None) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref="HEAD")
        metrics = self.observability.metrics(
            index_status=_safe_index_status(self),
            backend=_backend_name(self.backend),
            current_branch=self.backend.versions.current_branch(),
        )
        metrics["release"] = self.release()
        return metrics

    def prune_status(self, *, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.status(retention_days=retention_days)

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.prune(dry_run=dry_run, retention_days=retention_days)

    def prune_audit(self, *, limit: int = 50) -> dict[str, Any]:
        return {"status": "ok", "entries": self.backend.maintenance.audit_log(limit=limit)}

    def _record_namespace(self, ref: str) -> str:
        return _record_namespace(self, ref)

    def _graph_for_write(
        self,
        *,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> tuple[CortexGraph, CortexGraph | None, str, str | None]:
        current_branch = self.backend.versions.current_branch()
        self._enforce_namespace(namespace, branch=current_branch)
        current_head = self.backend.versions.resolve_ref("HEAD")
        if ref != "HEAD":
            resolved_ref = self.backend.versions.resolve_ref(ref)
            if resolved_ref is None:
                raise ValueError(f"Unknown ref: {ref}")
            if current_head is not None and resolved_ref != current_head:
                raise ValueError("Object writes must target HEAD or the active branch head.")
        baseline_graph = self.backend.versions.checkout(current_head) if current_head else None
        current_graph = _copy_graph(baseline_graph) if baseline_graph is not None else CortexGraph()
        return current_graph, baseline_graph, current_branch, current_head

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
            for key, value in {"source": source, "method": method, **dict(metadata or {})}.items()
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
            for key, value in {"source": source, "method": method, **dict(metadata or {})}.items()
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

    def log(self, *, limit: int = 10, ref: str | None = None, namespace: str | None = None) -> dict[str, Any]:
        if ref is not None:
            self._enforce_namespace(namespace, ref=ref)
        versions = self.backend.versions.log(limit=limit, ref=ref)
        if namespace and ref is None:
            versions = [version for version in versions if self._branch_in_namespace(version.namespace, namespace)]
        return {
            "status": "ok",
            "ref": ref,
            "versions": [version.to_dict() for version in versions],
        }

    def list_branches(self, *, namespace: str | None = None) -> dict[str, Any]:
        branches = self.backend.versions.list_branches()
        if namespace:
            branches = [branch for branch in branches if self._branch_in_namespace(branch.name, namespace)]
        return {
            "status": "ok",
            "current_branch": self.backend.versions.current_branch(),
            "branches": [branch.to_dict() for branch in branches],
        }

    def create_branch(
        self,
        *,
        name: str,
        from_ref: str = "HEAD",
        switch: bool = False,
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._enforce_namespace(namespace, branch=name)
        self._enforce_namespace(namespace, ref=from_ref)
        self._authorize(actor=actor, action="branch", namespace=name, approve=approve)
        head = self.backend.versions.create_branch(name, from_ref=from_ref, switch=switch)
        return {
            "status": "ok",
            "branch": name,
            "head": head,
            "current_branch": self.backend.versions.current_branch(),
            "created": True,
        }

    def switch_branch(
        self,
        *,
        name: str,
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._enforce_namespace(namespace, branch=name)
        self._authorize(actor=actor, action="branch", namespace=name, approve=approve)
        head = self.backend.versions.switch_branch(name)
        return {
            "status": "ok",
            "branch": self.backend.versions.current_branch(),
            "head": head,
        }

    def checkout(self, *, ref: str = "HEAD", verify: bool = True, namespace: str | None = None) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref=ref)
        version_id = self.backend.versions.resolve_ref(ref)
        if version_id is None:
            raise ValueError(f"Unknown ref: {ref}")
        graph = self.backend.versions.checkout(version_id, verify=verify)
        return {
            "status": "ok",
            "ref": ref,
            "version_id": version_id,
            "graph": graph.export_v5(),
        }

    def diff(self, *, version_a: str, version_b: str, namespace: str | None = None) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref=version_a)
        self._enforce_namespace(namespace, ref=version_b)
        resolved_a = self.backend.versions.resolve_ref(version_a)
        resolved_b = self.backend.versions.resolve_ref(version_b)
        if resolved_a is None:
            raise ValueError(f"Unknown version: {version_a}")
        if resolved_b is None:
            raise ValueError(f"Unknown version: {version_b}")
        return {
            "status": "ok",
            "version_a": resolved_a,
            "version_b": resolved_b,
            **self.backend.versions.diff(resolved_a, resolved_b),
        }

    def commit(
        self,
        *,
        graph: dict[str, Any],
        message: str,
        source: str = "manual",
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph = _coerce_graph(graph)
        baseline_version = self.backend.versions.resolve_ref("HEAD")
        baseline_graph = self.backend.versions.checkout(baseline_version) if baseline_version else None
        namespace = namespace or self.backend.versions.current_branch()
        self._enforce_namespace(namespace, branch=self.backend.versions.current_branch())
        self._authorize(
            actor=actor,
            action="write",
            namespace=namespace,
            approve=approve,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        )
        record = self.backend.versions.commit(
            current_graph,
            message,
            source=source,
            identity=_load_identity(self.store_dir),
        )
        return {
            "status": "ok",
            "commit": record.to_dict(),
        }

    def review(
        self,
        *,
        against: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        fail_on: str = "blocking",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref=against)
        against_version = self.backend.versions.resolve_ref(against)
        if against_version is None:
            raise ValueError(f"Unknown baseline ref: {against}")
        against_graph = self.backend.versions.checkout(against_version)
        current_graph, current_label = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        fail_policies = parse_failure_policies(fail_on)
        review = review_graphs(current_graph, against_graph, current_label=current_label, against_label=against_version)
        result = review.to_dict()
        should_fail, failure_counts = review.should_fail(fail_policies)
        result["status"] = "fail" if should_fail else "pass"
        result["fail_on"] = fail_policies
        result["failure_counts"] = failure_counts
        return result

    def blame(
        self,
        *,
        label: str = "",
        node_id: str = "",
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, _ = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        return blame_memory_nodes(
            current_graph,
            label=label or None,
            node_id=node_id or None,
            store=self.backend.versions,
            ledger=self.backend.claims,
            ref=ref,
            source=source,
            version_limit=limit,
        )

    def history(
        self,
        *,
        label: str = "",
        node_id: str = "",
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        result = self.blame(
            label=label,
            node_id=node_id,
            graph=graph,
            ref=ref,
            source=source,
            limit=limit,
            namespace=namespace,
        )
        return {
            "status": "ok",
            "ref": ref,
            "source": source,
            "nodes": result["nodes"],
        }

    def query_category(
        self,
        *,
        tag: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        engine = QueryEngine(current_graph)
        nodes = engine.query_category(tag)
        return {
            "status": "ok",
            "graph_source": graph_source,
            "tag": tag,
            "nodes": [_node_payload(node) for node in nodes],
            "count": len(nodes),
        }

    def query_path(
        self,
        *,
        from_label: str,
        to_label: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        engine = QueryEngine(current_graph)
        paths = engine.query_path(from_label, to_label)
        serialized_paths = [[_node_payload(node) for node in path] for path in paths]
        return {
            "status": "ok",
            "graph_source": graph_source,
            "from_label": from_label,
            "to_label": to_label,
            "paths": serialized_paths,
            "count": len(serialized_paths),
            "found": bool(serialized_paths),
        }

    def query_related(
        self,
        *,
        label: str,
        depth: int = 2,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        engine = QueryEngine(current_graph)
        nodes = engine.query_related(label, depth=depth)
        return {
            "status": "ok",
            "graph_source": graph_source,
            "label": label,
            "depth": depth,
            "nodes": [_node_payload(node) for node in nodes],
            "count": len(nodes),
        }

    def query_search(
        self,
        *,
        query: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        limit: int = 10,
        min_score: float = 0.0,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        if graph is not None:
            current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
            results, search_meta = hybrid_search_documents(
                [node.to_dict() for node in current_graph.nodes.values()],
                query,
                limit=limit,
                min_score=min_score,
                provider=get_embedding_provider(),
            )
            search_backend = "payload_graph"
            persistent_index = False
        else:
            self._enforce_namespace(namespace, ref=ref)
            graph_source = self.backend.versions.resolve_ref(ref)
            if graph_source is None:
                raise ValueError(f"Unknown ref: {ref}")
            results = self.backend.indexing.search(query=query, ref=ref, limit=limit, min_score=min_score)
            index_status = self.backend.indexing.status(ref=ref)
            search_backend = "persistent_index" if index_status.get("persistent") else "graph_checkout"
            persistent_index = bool(index_status.get("persistent", False))
            search_meta = {
                "embedding_enabled": bool(index_status.get("embedding_enabled", False)),
                "embedding_provider": index_status.get("embedding_provider", "disabled"),
                "hybrid": bool(index_status.get("embedding_enabled", False)),
            }
        return {
            "status": "ok",
            "graph_source": graph_source,
            "query": query,
            "search_backend": search_backend,
            "persistent_index": persistent_index,
            "embedding_enabled": bool(search_meta.get("embedding_enabled", False)),
            "embedding_provider": search_meta.get("embedding_provider", "disabled"),
            "hybrid": bool(search_meta.get("hybrid", False)),
            "results": [
                {
                    "node": _node_payload(item["node"]),
                    "score": item["score"],
                    "sources": item.get("sources", []),
                }
                for item in results
            ],
            "count": len(results),
        }

    def index_status(self, *, ref: str = "HEAD", namespace: str | None = None) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref=ref)
        return self.backend.indexing.status(ref=ref)

    def index_rebuild(
        self, *, ref: str = "HEAD", all_refs: bool = False, namespace: str | None = None
    ) -> dict[str, Any]:
        if namespace and all_refs:
            raise PermissionError("Namespace-scoped clients cannot rebuild all refs at once.")
        self._enforce_namespace(namespace, ref=ref)
        return self.backend.indexing.rebuild(ref=ref, all_refs=all_refs)

    def query_dsl(
        self,
        *,
        query: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        try:
            result = execute_query(current_graph, query)
        except ParseError as exc:
            raise ValueError(str(exc)) from exc
        return {
            "status": "ok",
            "graph_source": graph_source,
            "query": query,
            **result,
        }

    def query_nl(
        self,
        *,
        query: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        engine = QueryEngine(current_graph)
        result = parse_nl_query(query, engine)
        if isinstance(result, str):
            return {
                "status": "ok",
                "graph_source": graph_source,
                "query": query,
                "recognized": False,
                "message": result,
            }
        return {
            "status": "ok",
            "graph_source": graph_source,
            "query": query,
            "recognized": True,
            "result": result,
        }

    def detect_conflicts(
        self,
        *,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        min_severity: float = 0.0,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        conflicts = list_memory_conflicts(current_graph, min_severity=min_severity)
        return {
            "status": "ok",
            "graph_source": graph_source,
            "ref": ref,
            "min_severity": min_severity,
            "conflicts": [conflict.to_dict() for conflict in conflicts],
            "count": len(conflicts),
        }

    def resolve_conflict(
        self,
        *,
        conflict_id: str,
        action: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref, namespace=namespace)
        result = resolve_memory_conflict(current_graph, conflict_id, action)
        if result.get("status") != "ok":
            error = result.get("error", "conflict resolution failed")
            raise ValueError(f"{error}: {conflict_id}")
        remaining = list_memory_conflicts(current_graph)
        return {
            "status": "ok",
            "graph_source": graph_source,
            "ref": ref,
            **result,
            "remaining_conflicts": len(remaining),
            "conflicts": [conflict.to_dict() for conflict in remaining],
            "graph": current_graph.export_v5(),
        }

    def merge_preview(
        self,
        *,
        other_ref: str,
        current_ref: str = "HEAD",
        persist: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref=current_ref)
        self._enforce_namespace(namespace, ref=other_ref)
        result = merge_refs(self.backend.versions, current_ref, other_ref)
        current_branch = self.backend.versions.current_branch() if current_ref == "HEAD" else current_ref
        payload = _merge_payload(
            current_ref=current_ref,
            current_branch=current_branch,
            other_ref=other_ref,
            result=result,
        )
        if persist:
            if current_ref != "HEAD":
                raise ValueError("Persistent merge preview only supports current_ref='HEAD'")
            if result.conflicts:
                state = save_merge_state(
                    self.store_dir,
                    current_branch=current_branch,
                    other_ref=other_ref,
                    result=result,
                )
                payload["pending_merge"] = True
                payload["pending_conflicts"] = len(state["conflicts"])
            else:
                clear_merge_state(self.store_dir)
                payload["pending_merge"] = False
                payload["pending_conflicts"] = 0
        return payload

    def merge_conflicts(self, *, namespace: str | None = None) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref="HEAD")
        return self._pending_merge_payload()

    def merge_resolve(
        self,
        *,
        conflict_id: str,
        choose: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref="HEAD")
        result = resolve_merge_conflict(self.backend.versions, self.store_dir, conflict_id, choose)
        payload = self._pending_merge_payload()
        payload.update(result)
        payload["status"] = "ok"
        return payload

    def merge_commit_resolved(
        self,
        *,
        message: str | None = None,
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            raise ValueError("No pending merge state found")
        self._enforce_namespace(namespace, branch=state["current_branch"])
        conflicts = state.get("conflicts", [])
        if conflicts:
            raise ValueError(f"Cannot commit merge; {len(conflicts)} conflict(s) remain.")

        graph = load_merge_worktree(self.store_dir)
        baseline_version = self.backend.versions.resolve_ref("HEAD")
        baseline_graph = self.backend.versions.checkout(baseline_version) if baseline_version else None
        self._authorize(
            actor=actor,
            action="merge",
            namespace=state["current_branch"],
            approve=approve,
            current_graph=graph,
            baseline_graph=baseline_graph,
        )

        merge_message = message or f"Merge branch '{state['other_ref']}' into {state['current_branch']}"
        merge_parent_ids = (
            [state["other_version"]]
            if state.get("other_version") and state.get("other_version") != state.get("current_version")
            else []
        )
        record = self.backend.versions.commit(
            graph,
            merge_message,
            source="merge",
            identity=_load_identity(self.store_dir),
            parent_id=state.get("current_version"),
            branch=state["current_branch"],
            merge_parent_ids=merge_parent_ids,
        )
        clear_merge_state(self.store_dir)
        return {
            "status": "ok",
            "commit_id": record.version_id,
            "message": merge_message,
            "commit": record.to_dict(),
        }

    def merge_abort(self, *, namespace: str | None = None) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            return {
                "status": "ok",
                "aborted": False,
                "pending": False,
            }
        self._enforce_namespace(namespace, branch=state["current_branch"])
        clear_merge_state(self.store_dir)
        return {
            "status": "ok",
            "aborted": True,
            "pending": False,
            "current_branch": state["current_branch"],
            "other_ref": state["other_ref"],
        }
