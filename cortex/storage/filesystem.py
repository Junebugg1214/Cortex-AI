from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cortex.claims import ClaimLedger
from cortex.governance import GovernanceRule, GovernanceStore
from cortex.graph import CortexGraph, Node
from cortex.remotes import MemoryRemote, RemoteRegistry, fork_remote, pull_remote, push_remote
from cortex.schemas.memory_v1 import (
    DEFAULT_TENANT_ID,
    BranchRecord,
    ClaimRecord,
    CommitRecord,
    GovernanceDecisionRecord,
    GovernanceRuleRecord,
    RemoteRecord,
)
from cortex.upai.versioning import VersionStore


def _to_governance_model(record: GovernanceRuleRecord) -> GovernanceRule:
    return GovernanceRule(
        name=record.name,
        effect=record.effect,
        actor_pattern=record.actor_pattern,
        actions=list(record.actions),
        namespaces=list(record.namespaces),
        require_approval=record.require_approval,
        approval_below_confidence=record.approval_below_confidence,
        approval_tags=list(record.approval_tags),
        approval_change_types=list(record.approval_change_types),
        description=record.description,
    )


def _to_remote_model(record: RemoteRecord) -> MemoryRemote:
    return MemoryRemote(
        name=record.name,
        path=record.path,
        default_branch=record.default_branch,
    )


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

    def checkout(self, version_id: str, verify: bool = True) -> CortexGraph:
        return self.store.checkout(version_id, verify=verify)

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
        return [CommitRecord.from_context_version(item, tenant_id=self.tenant_id) for item in self.store.log(limit, ref)]

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


@dataclass(slots=True)
class FilesystemClaimBackend:
    ledger: ClaimLedger
    versions: FilesystemVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

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
    ) -> list[ClaimRecord]:
        namespace = self.versions.current_branch()
        events = self.ledger.list_events(
            claim_id=claim_id,
            node_id=node_id,
            canonical_id=canonical_id,
            label=label,
            source=source,
            version_ref=version_ref,
            op=op,
            limit=limit,
        )
        return [
            ClaimRecord.from_claim_event(event, tenant_id=self.tenant_id, namespace=namespace)
            for event in events
        ]

    def lineage_for_node(
        self,
        node: Node,
        limit: int = 50,
        *,
        source: str = "",
        version_ref: str = "",
    ) -> dict[str, Any]:
        return self.ledger.lineage_for_node(node, limit=limit, source=source, version_ref=version_ref)


@dataclass(slots=True)
class FilesystemGovernanceBackend:
    store: GovernanceStore
    tenant_id: str = DEFAULT_TENANT_ID

    def list_rules(self) -> list[GovernanceRuleRecord]:
        return [GovernanceRuleRecord.from_governance_rule(rule, tenant_id=self.tenant_id) for rule in self.store.list_rules()]

    def upsert_rule(self, rule: GovernanceRuleRecord) -> None:
        self.store.upsert_rule(_to_governance_model(rule))

    def remove_rule(self, name: str) -> bool:
        return self.store.remove_rule(name)

    def authorize(
        self,
        actor: str,
        action: str,
        namespace: str,
        *,
        current_graph: CortexGraph | None = None,
        baseline_graph: CortexGraph | None = None,
    ) -> GovernanceDecisionRecord:
        decision = self.store.authorize(
            actor,
            action,
            namespace,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        )
        return GovernanceDecisionRecord.from_governance_decision(decision, tenant_id=self.tenant_id)


@dataclass(slots=True)
class FilesystemRemoteBackend:
    registry: RemoteRegistry
    versions: FilesystemVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def list_remotes(self) -> list[RemoteRecord]:
        return [RemoteRecord.from_memory_remote(remote, tenant_id=self.tenant_id) for remote in self.registry.list_remotes()]

    def add_remote(self, remote: RemoteRecord) -> None:
        self.registry.add(_to_remote_model(remote))

    def remove_remote(self, name: str) -> bool:
        return self.registry.remove(name)

    def push_remote(
        self,
        name: str,
        *,
        branch: str,
        target_branch: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        remote = self.registry.get(name)
        if remote is None:
            raise ValueError(f"Unknown remote: {name}")
        return push_remote(
            self.versions.store,
            remote,
            branch=branch,
            target_branch=target_branch,
            force=force,
        )

    def pull_remote(
        self,
        name: str,
        *,
        branch: str,
        into_branch: str | None = None,
        force: bool = False,
        switch: bool = False,
    ) -> dict[str, Any]:
        remote = self.registry.get(name)
        if remote is None:
            raise ValueError(f"Unknown remote: {name}")
        return pull_remote(
            self.versions.store,
            remote,
            branch=branch,
            into_branch=into_branch,
            force=force,
            switch=switch,
        )

    def fork_remote(
        self,
        name: str,
        *,
        remote_branch: str,
        local_branch: str,
        switch: bool = False,
    ) -> dict[str, Any]:
        remote = self.registry.get(name)
        if remote is None:
            raise ValueError(f"Unknown remote: {name}")
        return fork_remote(
            self.versions.store,
            remote,
            remote_branch=remote_branch,
            local_branch=local_branch,
            switch=switch,
        )


@dataclass(slots=True)
class FilesystemStorageBackend:
    store_dir: Path
    tenant_id: str = DEFAULT_TENANT_ID
    versions: FilesystemVersionBackend = field(init=False)
    claims: FilesystemClaimBackend = field(init=False)
    governance: FilesystemGovernanceBackend = field(init=False)
    remotes: FilesystemRemoteBackend = field(init=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        versions = FilesystemVersionBackend(VersionStore(self.store_dir), tenant_id=self.tenant_id)
        self.versions = versions
        self.claims = FilesystemClaimBackend(ClaimLedger(self.store_dir), versions, tenant_id=self.tenant_id)
        self.governance = FilesystemGovernanceBackend(GovernanceStore(self.store_dir), tenant_id=self.tenant_id)
        self.remotes = FilesystemRemoteBackend(RemoteRegistry(self.store_dir), versions, tenant_id=self.tenant_id)


def build_filesystem_backend(
    store_dir: str | Path,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> FilesystemStorageBackend:
    return FilesystemStorageBackend(Path(store_dir), tenant_id=tenant_id)


__all__ = [
    "FilesystemClaimBackend",
    "FilesystemGovernanceBackend",
    "FilesystemRemoteBackend",
    "FilesystemStorageBackend",
    "FilesystemVersionBackend",
    "build_filesystem_backend",
]
