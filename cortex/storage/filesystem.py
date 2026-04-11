from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cortex.claims import ClaimEvent, ClaimLedger
from cortex.governance import GovernanceRule, GovernanceStore
from cortex.graph import CortexGraph, Node
from cortex.remote_trust import prepare_remote_fields
from cortex.remotes import MemoryRemote, RemoteRegistry
from cortex.schemas.memory_v1 import (
    DEFAULT_TENANT_ID,
    ClaimRecord,
    GovernanceDecisionRecord,
    GovernanceRuleRecord,
    RemoteRecord,
)
from cortex.storage.filesystem_indexing import FilesystemIndexBackend, FilesystemMaintenanceBackend
from cortex.storage.filesystem_versions import FilesystemVersionBackend
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
    prepared = prepare_remote_fields(record)
    return MemoryRemote(
        name=record.name,
        path=record.path,
        default_branch=record.default_branch,
        trusted_did=prepared["trusted_did"],
        trusted_public_key_b64=prepared["trusted_public_key_b64"],
        allowed_namespaces=list(prepared["allowed_namespaces"]),
    )


@dataclass(slots=True)
class FilesystemClaimBackend:
    ledger: ClaimLedger
    versions: FilesystemVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def append(self, event: Any) -> None:
        claim_event = event if isinstance(event, ClaimEvent) else ClaimEvent.from_dict(event.to_dict())
        self.ledger.append(claim_event)

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
        return [ClaimRecord.from_claim_event(event, tenant_id=self.tenant_id, namespace=namespace) for event in events]

    def lineage_for_node(
        self,
        node: Node,
        limit: int = 50,
        *,
        source: str = "",
        version_ref: str = "",
    ) -> dict[str, Any]:
        return self.ledger.lineage_for_node(node, limit=limit, source=source, version_ref=version_ref)

    def get_claim(self, claim_id: str) -> list[ClaimRecord]:
        namespace = self.versions.current_branch()
        return [
            ClaimRecord.from_claim_event(event, tenant_id=self.tenant_id, namespace=namespace)
            for event in self.ledger.get_claim(claim_id)
        ]

    def latest_event(self, claim_id: str) -> ClaimRecord | None:
        event = self.ledger.latest_event(claim_id)
        if event is None:
            return None
        return ClaimRecord.from_claim_event(
            event,
            tenant_id=self.tenant_id,
            namespace=self.versions.current_branch(),
        )


@dataclass(slots=True)
class FilesystemGovernanceBackend:
    store: GovernanceStore
    tenant_id: str = DEFAULT_TENANT_ID

    def list_rules(self) -> list[GovernanceRuleRecord]:
        return [
            GovernanceRuleRecord.from_governance_rule(rule, tenant_id=self.tenant_id)
            for rule in self.store.list_rules()
        ]

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

    def _require_remote(self, name: str) -> RemoteRecord:
        for remote in self.list_remotes():
            if remote.name == name:
                if not remote.trusted_did or not remote.trusted_public_key_b64 or not remote.allowed_namespaces:
                    self.add_remote(remote)
                    return next(item for item in self.list_remotes() if item.name == name)
                return remote
        raise ValueError(f"Unknown remote: {name}")

    def list_remotes(self) -> list[RemoteRecord]:
        return [
            RemoteRecord.from_memory_remote(remote, tenant_id=self.tenant_id) for remote in self.registry.list_remotes()
        ]

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
        from cortex.storage.remote_sync import push_remote_backend

        return push_remote_backend(self.storage_backend, self._require_remote(name), branch, target_branch, force)

    def pull_remote(
        self,
        name: str,
        *,
        branch: str,
        into_branch: str | None = None,
        force: bool = False,
        switch: bool = False,
    ) -> dict[str, Any]:
        from cortex.storage.remote_sync import pull_remote_backend

        return pull_remote_backend(self.storage_backend, self._require_remote(name), branch, into_branch, force, switch)

    def fork_remote(
        self,
        name: str,
        *,
        remote_branch: str,
        local_branch: str,
        switch: bool = False,
    ) -> dict[str, Any]:
        from cortex.storage.remote_sync import fork_remote_backend

        return fork_remote_backend(
            self.storage_backend, self._require_remote(name), remote_branch, local_branch, switch
        )

    @property
    def storage_backend(self) -> "FilesystemStorageBackend":
        return FilesystemStorageBackend(self.versions.store.store_dir, tenant_id=self.tenant_id)


@dataclass(slots=True)
class FilesystemStorageBackend:
    store_dir: Path
    tenant_id: str = DEFAULT_TENANT_ID
    versions: FilesystemVersionBackend = field(init=False)
    claims: FilesystemClaimBackend = field(init=False)
    governance: FilesystemGovernanceBackend = field(init=False)
    remotes: FilesystemRemoteBackend = field(init=False)
    indexing: FilesystemIndexBackend = field(init=False)
    maintenance: FilesystemMaintenanceBackend = field(init=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        versions = FilesystemVersionBackend(VersionStore(self.store_dir), tenant_id=self.tenant_id)
        self.versions = versions
        self.claims = FilesystemClaimBackend(ClaimLedger(self.store_dir), versions, tenant_id=self.tenant_id)
        self.governance = FilesystemGovernanceBackend(GovernanceStore(self.store_dir), tenant_id=self.tenant_id)
        self.remotes = FilesystemRemoteBackend(RemoteRegistry(self.store_dir), versions, tenant_id=self.tenant_id)
        self.indexing = FilesystemIndexBackend(versions)
        self.maintenance = FilesystemMaintenanceBackend(self.store_dir)


def build_filesystem_backend(
    store_dir: str | Path,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> FilesystemStorageBackend:
    return FilesystemStorageBackend(Path(store_dir), tenant_id=tenant_id)


__all__ = [
    "FilesystemClaimBackend",
    "FilesystemGovernanceBackend",
    "FilesystemIndexBackend",
    "FilesystemMaintenanceBackend",
    "FilesystemRemoteBackend",
    "FilesystemStorageBackend",
    "FilesystemVersionBackend",
    "build_filesystem_backend",
]
