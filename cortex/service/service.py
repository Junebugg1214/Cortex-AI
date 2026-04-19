"""MemoryService final MRO:

MemoryService -> MemoryRuntimeAgentMixin -> MemoryRuntimeMetaMixin ->
MemoryRuntimeMindMixin -> MemoryRuntimePackMixin -> MemoryGraphMergeServiceMixin ->
MemoryGraphQueryServiceMixin -> MemoryObjectServiceMixin -> object.

Channel and portability helpers are implemented directly on MemoryService; the
previous empty aggregate mixins are intentionally absent from the MRO.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from cortex.graph.graph import CortexGraph
from cortex.observability import CortexObservability
from cortex.portability.portable_runtime import (
    audit_portability,
    render_portability_context,
    scan_portability,
    status_portability,
)
from cortex.security.secrets import SecretsScanner
from cortex.service.service_common import _coerce_graph
from cortex.service.service_graph_merge import MemoryGraphMergeServiceMixin
from cortex.service.service_graph_queries import MemoryGraphQueryServiceMixin
from cortex.service.service_objects import MemoryObjectServiceMixin
from cortex.service.service_runtime_agents import MemoryRuntimeAgentMixin
from cortex.service.service_runtime_meta import MemoryRuntimeMetaMixin
from cortex.service.service_runtime_minds import MemoryRuntimeMindMixin
from cortex.service.service_runtime_packs import MemoryRuntimePackMixin
from cortex.storage import get_storage_backend
from cortex.storage.base import StorageBackend


@dataclass(slots=True)
class MemoryService(
    MemoryRuntimeAgentMixin,
    MemoryRuntimeMetaMixin,
    MemoryRuntimeMindMixin,
    MemoryRuntimePackMixin,
    MemoryGraphMergeServiceMixin,
    MemoryGraphQueryServiceMixin,
    MemoryObjectServiceMixin,
):
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

    def portability_context(
        self,
        *,
        target: str,
        project_dir: str = "",
        smart: bool | None = None,
        policy: str | None = None,
        max_chars: int = 1500,
    ) -> dict[str, object]:
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
    ) -> dict[str, object]:
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
    ) -> dict[str, object]:
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
    ) -> dict[str, object]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = audit_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
        )
        payload["release"] = self.release()
        return payload

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
