from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cortex.graph.graph import CortexGraph
from cortex.schemas.memory_v1 import (
    DEFAULT_TENANT_ID,
    BranchRecord,
    CommitRecord,
)
from cortex.versioning.upai.versioning import VersionStore


@dataclass(slots=True)
class FilesystemVersionBackend:
    store: VersionStore
    tenant_id: str = DEFAULT_TENANT_ID

    def current_branch(self) -> str:
        return self.store.current_branch()

    def resolve_ref(self, ref: str) -> str | None:
        return self.store.resolve_ref(ref)

    def resolve_at(self, timestamp: str, ref: str | None = None) -> str | None:
        return self.store.resolve_at(timestamp, ref=ref)

    def is_ancestor(self, ancestor_ref: str, descendant_ref: str) -> bool:
        return self.store.is_ancestor(ancestor_ref, descendant_ref)

    def merge_base(self, ref_a: str, ref_b: str) -> str | None:
        return self.store.merge_base(ref_a, ref_b)

    def checkout(self, version_id: str, verify: bool = True) -> CortexGraph:
        return self.store.checkout(version_id, verify=verify)

    def diff(self, version_id_a: str, version_id_b: str) -> dict[str, Any]:
        return self.store.diff(version_id_a, version_id_b)

    def verify_chain_integrity(self) -> dict[str, Any]:
        return self.store.verify_chain_integrity()

    def head(self, ref: str = "HEAD") -> CommitRecord | None:
        version = self.store.head(ref=ref)
        return None if version is None else CommitRecord.from_context_version(version, tenant_id=self.tenant_id)

    def commit(
        self,
        graph: CortexGraph,
        message: str,
        source: str = "manual",
        identity: Any | None = None,
        *,
        parent_id: str | None = None,
        branch: str | None = None,
        merge_parent_ids: list[str] | None = None,
    ) -> CommitRecord:
        version = self.store.commit(
            graph,
            message,
            source=source,
            identity=identity,
            parent_id=parent_id,
            branch=branch,
            merge_parent_ids=merge_parent_ids,
        )
        return CommitRecord.from_context_version(version, tenant_id=self.tenant_id)

    def log(self, limit: int = 10, ref: str | None = None) -> list[CommitRecord]:
        return [
            CommitRecord.from_context_version(item, tenant_id=self.tenant_id) for item in self.store.log(limit, ref)
        ]

    def list_branches(self) -> list[BranchRecord]:
        return [BranchRecord.from_branch_payload(item, tenant_id=self.tenant_id) for item in self.store.list_branches()]

    def create_branch(self, branch_name: str, from_ref: str = "HEAD", switch: bool = False) -> str | None:
        return self.store.create_branch(branch_name, from_ref=from_ref, switch=switch)

    def switch_branch(self, branch_name: str) -> str | None:
        return self.store.switch_branch(branch_name)

    def blame_node(
        self,
        *,
        node_id: str = "",
        label: str = "",
        aliases: list[str] | None = None,
        canonical_id: str = "",
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.store.blame_node(
            node_id=node_id,
            label=label,
            aliases=aliases,
            canonical_id=canonical_id,
            ref=ref,
            source=source,
            limit=limit,
        )
