from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from cortex.graph import CortexGraph, Node
from cortex.schemas.memory_v1 import (
    DEFAULT_NAMESPACE,
    DEFAULT_TENANT_ID,
    BranchRecord,
    ClaimRecord,
    CommitRecord,
    GovernanceDecisionRecord,
    GovernanceRuleRecord,
    RemoteRecord,
)


class VersionBackend(Protocol):
    def current_branch(self) -> str: ...
    def resolve_ref(self, ref: str) -> str | None: ...
    def resolve_at(self, timestamp: str, ref: str | None = None) -> str | None: ...
    def checkout(self, version_id: str, verify: bool = True) -> CortexGraph: ...
    def head(self, ref: str = "HEAD") -> CommitRecord | None: ...
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
    ) -> CommitRecord: ...
    def log(self, limit: int = 10, ref: str | None = None) -> list[CommitRecord]: ...
    def list_branches(self) -> list[BranchRecord]: ...
    def create_branch(self, branch_name: str, from_ref: str = "HEAD", switch: bool = False) -> str | None: ...
    def switch_branch(self, branch_name: str) -> str | None: ...
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
    ) -> dict[str, Any]: ...


class ClaimBackend(Protocol):
    def list_events(
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
    ) -> list[ClaimRecord]: ...
    def lineage_for_node(
        self,
        node: Node,
        limit: int = 50,
        *,
        source: str = "",
        version_ref: str = "",
    ) -> dict[str, Any]: ...


class GovernanceBackend(Protocol):
    def list_rules(self) -> list[GovernanceRuleRecord]: ...
    def upsert_rule(self, rule: GovernanceRuleRecord) -> None: ...
    def remove_rule(self, name: str) -> bool: ...
    def authorize(
        self,
        actor: str,
        action: str,
        namespace: str,
        *,
        current_graph: CortexGraph | None = None,
        baseline_graph: CortexGraph | None = None,
    ) -> GovernanceDecisionRecord: ...


class RemoteBackend(Protocol):
    def list_remotes(self) -> list[RemoteRecord]: ...
    def add_remote(self, remote: RemoteRecord) -> None: ...
    def remove_remote(self, name: str) -> bool: ...
    def push_remote(
        self,
        name: str,
        *,
        branch: str,
        target_branch: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]: ...
    def pull_remote(
        self,
        name: str,
        *,
        branch: str,
        into_branch: str | None = None,
        force: bool = False,
        switch: bool = False,
    ) -> dict[str, Any]: ...
    def fork_remote(
        self,
        name: str,
        *,
        remote_branch: str,
        local_branch: str,
        switch: bool = False,
    ) -> dict[str, Any]: ...


class StorageBackend(Protocol):
    store_dir: Path
    tenant_id: str
    versions: VersionBackend
    claims: ClaimBackend
    governance: GovernanceBackend
    remotes: RemoteBackend


__all__ = [
    "DEFAULT_NAMESPACE",
    "DEFAULT_TENANT_ID",
    "ClaimBackend",
    "GovernanceBackend",
    "RemoteBackend",
    "StorageBackend",
    "VersionBackend",
]
