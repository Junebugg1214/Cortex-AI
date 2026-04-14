from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from cortex.graph import CortexGraph
from cortex.observability import CortexObservability
from cortex.security.secrets import SecretsScanner
from cortex.service_common import _coerce_graph
from cortex.service_objects import MemoryObjectServiceMixin
from cortex.service_runtime import MemoryRuntimeServiceMixin
from cortex.service_versioned_graph import MemoryVersionedGraphServiceMixin
from cortex.storage import get_storage_backend
from cortex.storage.base import StorageBackend


@dataclass(slots=True)
class MemoryService(MemoryRuntimeServiceMixin, MemoryVersionedGraphServiceMixin, MemoryObjectServiceMixin):
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
        self.started_at = monotonic()
        head = self.backend.versions.resolve_ref("HEAD")
        if head is not None:
            SecretsScanner().warn_if_graph_contains_secrets(
                self.backend.versions.checkout(head),
                operation="service_startup",
            )

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
        current_graph = CortexGraph.from_v5_json(baseline_graph.export_v5()) if baseline_graph else CortexGraph()
        return current_graph, baseline_graph, current_branch, current_head


__all__ = ["MemoryService"]
