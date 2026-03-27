from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cortex.claims import ClaimEvent, ClaimLedger
from cortex.embeddings import get_embedding_provider, hybrid_search_documents
from cortex.governance import GovernanceRule, GovernanceStore
from cortex.graph import CortexGraph, Node
from cortex.remotes import MemoryRemote, RemoteRegistry
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

    def is_ancestor(self, ancestor_ref: str, descendant_ref: str) -> bool:
        return self.store.is_ancestor(ancestor_ref, descendant_ref)

    def merge_base(self, ref_a: str, ref_b: str) -> str | None:
        return self.store.merge_base(ref_a, ref_b)

    def checkout(self, version_id: str, verify: bool = True) -> CortexGraph:
        return self.store.checkout(version_id, verify=verify)

    def diff(self, version_id_a: str, version_id_b: str) -> dict[str, Any]:
        return self.store.diff(version_id_a, version_id_b)

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
class FilesystemIndexBackend:
    versions: FilesystemVersionBackend

    def status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        resolved_ref = self.versions.resolve_ref(ref)
        if resolved_ref is None:
            raise ValueError(f"Unknown ref: {ref}")
        graph = self.versions.checkout(resolved_ref)
        provider = get_embedding_provider()
        return {
            "status": "ok",
            "backend": "filesystem",
            "persistent": False,
            "supported": False,
            "ref": ref,
            "resolved_ref": resolved_ref,
            "last_indexed_commit": None,
            "doc_count": len(graph.nodes),
            "stale": False,
            "updated_at": None,
            "lag_commits": 0,
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
        }

    def rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        if all_refs:
            indexed_versions = sorted({branch.head for branch in self.versions.list_branches() if branch.head})
        else:
            resolved_ref = self.versions.resolve_ref(ref)
            if resolved_ref is None:
                raise ValueError(f"Unknown ref: {ref}")
            indexed_versions = [resolved_ref]
        return {
            "status": "ok",
            "backend": "filesystem",
            "persistent": False,
            "supported": False,
            "ref": ref,
            "all_refs": all_refs,
            "rebuilt": 0,
            "indexed_versions": indexed_versions,
            "last_indexed_commit": None,
            "message": "Persistent lexical indexing is only available for sqlite-backed stores.",
            "embedding_provider": get_embedding_provider().name,
        }

    def search(
        self,
        *,
        query: str,
        ref: str = "HEAD",
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        resolved_ref = self.versions.resolve_ref(ref)
        if resolved_ref is None:
            raise ValueError(f"Unknown ref: {ref}")
        graph = self.versions.checkout(resolved_ref)
        results, _ = hybrid_search_documents(
            [node.to_dict() for node in graph.nodes.values()],
            query,
            limit=limit,
            min_score=min_score,
            provider=get_embedding_provider(),
        )
        return results


@dataclass(slots=True)
class FilesystemMaintenanceBackend:
    store_dir: Path
    audit_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.audit_path = self.store_dir / "maintenance_audit.json"

    def _merge_artifacts(self) -> list[Path]:
        return [self.store_dir / "merge_state.json", self.store_dir / "merge_working.json"]

    def _load_audit(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return list(json.loads(self.audit_path.read_text(encoding="utf-8")))

    def _write_audit(self, entries: list[dict[str, Any]]) -> None:
        self.audit_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def status(self, *, retention_days: int = 7) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(retention_days, 0))
        stale_merge_artifacts: list[str] = []
        for path in self._merge_artifacts():
            if not path.exists():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified <= cutoff:
                stale_merge_artifacts.append(str(path))
        return {
            "status": "ok",
            "backend": "filesystem",
            "retention_days": retention_days,
            "stale_merge_artifacts": stale_merge_artifacts,
            "orphan_lexical_indices": 0,
            "orphan_embedding_indices": 0,
            "stale_total": len(stale_merge_artifacts),
        }

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        status = self.status(retention_days=retention_days)
        removed_merge_artifacts: list[str] = []
        if not dry_run:
            for raw_path in status["stale_merge_artifacts"]:
                path = Path(raw_path)
                if path.exists():
                    path.unlink()
                    removed_merge_artifacts.append(raw_path)
            audit_entries = self._load_audit()
            audit_entries.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "prune",
                    "dry_run": False,
                    "retention_days": retention_days,
                    "removed_merge_artifacts": removed_merge_artifacts,
                }
            )
            self._write_audit(audit_entries[-100:])
        return {
            "status": "ok",
            "backend": "filesystem",
            "dry_run": dry_run,
            "retention_days": retention_days,
            "removed_merge_artifacts": removed_merge_artifacts,
            "stale_merge_artifacts": status["stale_merge_artifacts"],
            "orphan_lexical_indices": 0,
            "orphan_embedding_indices": 0,
        }

    def audit_log(self, *, limit: int = 50) -> list[dict[str, Any]]:
        entries = self._load_audit()
        return list(reversed(entries[-limit:]))


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
