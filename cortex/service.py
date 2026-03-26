from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cortex.compat import upgrade_v4_to_v5
from cortex.graph import CortexGraph
from cortex.memory_ops import blame_memory_nodes, list_memory_conflicts, resolve_memory_conflict
from cortex.merge import (
    clear_merge_state,
    load_merge_state,
    load_merge_worktree,
    merge_refs,
    resolve_merge_conflict,
    save_merge_state,
)
from cortex.openapi import build_openapi_spec
from cortex.query import QueryEngine, parse_nl_query
from cortex.query_lang import ParseError, execute_query
from cortex.review import parse_failure_policies, review_graphs
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


@dataclass(slots=True)
class MemoryService:
    store_dir: Path
    backend: StorageBackend
    context_file: Path | None = None

    def __init__(
        self,
        store_dir: str | Path = ".cortex",
        *,
        context_file: str | Path | None = None,
        backend: StorageBackend | None = None,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.context_file = Path(context_file).resolve() if context_file else None
        self.backend = backend or get_storage_backend(self.store_dir)

    def _default_graph_ref(self) -> str:
        return "HEAD"

    def _graph_from_request(
        self,
        *,
        graph: dict[str, Any] | None = None,
        ref: str | None = None,
    ) -> tuple[CortexGraph, str]:
        if graph is not None:
            return _coerce_graph(graph), "payload"
        version_ref = ref or self._default_graph_ref()
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
        return {
            "status": "ok",
            "backend": _backend_name(self.backend),
            "store_dir": str(self.store_dir.resolve()),
            "current_branch": self.backend.versions.current_branch(),
            "head": self.backend.versions.resolve_ref("HEAD"),
        }

    def openapi(self, *, server_url: str | None = None) -> dict[str, Any]:
        return build_openapi_spec(server_url=server_url)

    def meta(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "store_dir": str(self.store_dir.resolve()),
            "context_file": str(self.context_file) if self.context_file else "",
            "backend": _backend_name(self.backend),
            "current_branch": self.backend.versions.current_branch(),
            "head": self.backend.versions.resolve_ref("HEAD"),
        }

    def log(self, *, limit: int = 10, ref: str | None = None) -> dict[str, Any]:
        versions = self.backend.versions.log(limit=limit, ref=ref)
        return {
            "status": "ok",
            "ref": ref,
            "versions": [version.to_dict() for version in versions],
        }

    def list_branches(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "current_branch": self.backend.versions.current_branch(),
            "branches": [branch.to_dict() for branch in self.backend.versions.list_branches()],
        }

    def create_branch(
        self,
        *,
        name: str,
        from_ref: str = "HEAD",
        switch: bool = False,
        actor: str = "manual",
        approve: bool = False,
    ) -> dict[str, Any]:
        self._authorize(actor=actor, action="branch", namespace=name, approve=approve)
        head = self.backend.versions.create_branch(name, from_ref=from_ref, switch=switch)
        return {
            "status": "ok",
            "branch": name,
            "head": head,
            "current_branch": self.backend.versions.current_branch(),
            "created": True,
        }

    def switch_branch(self, *, name: str, actor: str = "manual", approve: bool = False) -> dict[str, Any]:
        self._authorize(actor=actor, action="branch", namespace=name, approve=approve)
        head = self.backend.versions.switch_branch(name)
        return {
            "status": "ok",
            "branch": self.backend.versions.current_branch(),
            "head": head,
        }

    def checkout(self, *, ref: str = "HEAD", verify: bool = True) -> dict[str, Any]:
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

    def diff(self, *, version_a: str, version_b: str) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
        current_graph = _coerce_graph(graph)
        baseline_version = self.backend.versions.resolve_ref("HEAD")
        baseline_graph = self.backend.versions.checkout(baseline_version) if baseline_version else None
        namespace = self.backend.versions.current_branch()
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
    ) -> dict[str, Any]:
        against_version = self.backend.versions.resolve_ref(against)
        if against_version is None:
            raise ValueError(f"Unknown baseline ref: {against}")
        against_graph = self.backend.versions.checkout(against_version)
        current_graph, current_label = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        current_graph, _ = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        result = self.blame(
            label=label,
            node_id=node_id,
            graph=graph,
            ref=ref,
            source=source,
            limit=limit,
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
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        if graph is not None:
            current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
            results = current_graph.semantic_search(query, limit=limit, min_score=min_score)
            search_backend = "payload_graph"
            persistent_index = False
        else:
            graph_source = self.backend.versions.resolve_ref(ref)
            if graph_source is None:
                raise ValueError(f"Unknown ref: {ref}")
            results = self.backend.indexing.search(query=query, ref=ref, limit=limit, min_score=min_score)
            index_status = self.backend.indexing.status(ref=ref)
            search_backend = "persistent_index" if index_status.get("persistent") else "graph_checkout"
            persistent_index = bool(index_status.get("persistent", False))
        return {
            "status": "ok",
            "graph_source": graph_source,
            "query": query,
            "search_backend": search_backend,
            "persistent_index": persistent_index,
            "results": [
                {
                    "node": _node_payload(item["node"]),
                    "score": item["score"],
                }
                for item in results
            ],
            "count": len(results),
        }

    def index_status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        return self.backend.indexing.status(ref=ref)

    def index_rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        return self.backend.indexing.rebuild(ref=ref, all_refs=all_refs)

    def query_dsl(
        self,
        *,
        query: str,
        graph: dict[str, Any] | None = None,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
        current_graph, graph_source = self._graph_from_request(graph=graph, ref=ref)
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
    ) -> dict[str, Any]:
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

    def merge_conflicts(self) -> dict[str, Any]:
        return self._pending_merge_payload()

    def merge_resolve(
        self,
        *,
        conflict_id: str,
        choose: str,
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            raise ValueError("No pending merge state found")
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

    def merge_abort(self) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            return {
                "status": "ok",
                "aborted": False,
                "pending": False,
            }
        clear_merge_state(self.store_dir)
        return {
            "status": "ok",
            "aborted": True,
            "pending": False,
            "current_branch": state["current_branch"],
            "other_ref": state["other_ref"],
        }
