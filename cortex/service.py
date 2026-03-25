from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cortex.compat import upgrade_v4_to_v5
from cortex.graph import CortexGraph
from cortex.memory_ops import blame_memory_nodes
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

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": _backend_name(self.backend),
            "store_dir": str(self.store_dir.resolve()),
            "current_branch": self.backend.versions.current_branch(),
            "head": self.backend.versions.resolve_ref("HEAD"),
        }

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
