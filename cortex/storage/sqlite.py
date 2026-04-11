from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cortex.claims import ClaimEvent
from cortex.governance import GovernanceRule
from cortex.graph import CortexGraph, Node, _normalize_label, diff_graphs
from cortex.remote_trust import _normalize_store_path, prepare_remote_fields
from cortex.schemas.memory_v1 import (
    DEFAULT_TENANT_ID,
    ClaimRecord,
    GovernanceDecisionRecord,
    GovernanceRuleRecord,
    RemoteRecord,
)
from cortex.semantic_diff import semantic_diff_graphs
from cortex.storage.sqlite_indexing import SQLiteIndexBackend, SQLiteMaintenanceBackend
from cortex.storage.sqlite_versions import (
    DEFAULT_SQLITE_FILENAME,
    SQLiteVersionBackend,
    sqlite_db_path,
)


@dataclass(slots=True)
class SQLiteClaimBackend:
    versions: SQLiteVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def append(self, event: Any) -> None:
        claim_event = event if isinstance(event, ClaimEvent) else ClaimEvent.from_dict(event.to_dict())
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO claims(event_id, payload) VALUES(?, ?)",
                (claim_event.event_id, json.dumps(claim_event.to_dict(), ensure_ascii=False)),
            )

    def _load_all(self) -> list[ClaimEvent]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM claims ORDER BY seq ASC").fetchall()
        return [ClaimEvent.from_dict(json.loads(row["payload"])) for row in rows]

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
        events = self._load_all()
        label_norm = _normalize_label(label) if label else ""
        filtered: list[ClaimEvent] = []
        for event in reversed(events):
            if claim_id and event.claim_id != claim_id:
                continue
            if node_id and event.node_id != node_id:
                continue
            if canonical_id and event.canonical_id != canonical_id:
                continue
            if label_norm:
                event_terms = {_normalize_label(event.label), *(_normalize_label(alias) for alias in event.aliases)}
                if label_norm not in event_terms:
                    continue
            if source and event.source != source:
                continue
            if version_ref and not event.version_id.startswith(version_ref):
                continue
            if op and event.op != op:
                continue
            filtered.append(event)
            if len(filtered) >= limit:
                break
        namespace = self.versions.current_branch()
        return [
            ClaimRecord.from_claim_event(event, tenant_id=self.tenant_id, namespace=namespace) for event in filtered
        ]

    def get_claim(self, claim_id: str) -> list[ClaimRecord]:
        namespace = self.versions.current_branch()
        return [
            ClaimRecord.from_claim_event(event, tenant_id=self.tenant_id, namespace=namespace)
            for event in self._load_all()
            if event.claim_id == claim_id
        ]

    def latest_event(self, claim_id: str) -> ClaimRecord | None:
        claims = self.get_claim(claim_id)
        return claims[-1] if claims else None

    def lineage_for_node(
        self,
        node: Node,
        limit: int = 50,
        *,
        source: str = "",
        version_ref: str = "",
    ) -> dict[str, Any]:
        events = [
            ClaimEvent.from_dict(item.to_dict())
            for item in self.list_events(
                node_id=node.id,
                canonical_id=node.canonical_id or node.id,
                label=node.label,
                source=source,
                version_ref=version_ref,
                limit=limit,
            )
        ]
        if not events and node.aliases:
            combined: list[ClaimEvent] = []
            seen: set[str] = set()
            for alias in node.aliases:
                for item in self.list_events(label=alias, source=source, version_ref=version_ref, limit=limit):
                    event = ClaimEvent.from_dict(item.to_dict())
                    if event.event_id in seen:
                        continue
                    seen.add(event.event_id)
                    combined.append(event)
            combined.sort(key=lambda event: event.timestamp, reverse=True)
            events = combined[:limit]
        if not events:
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
        chronological = list(reversed(events))
        claim_ids = sorted({event.claim_id for event in events})
        sources = sorted({event.source for event in events if event.source})
        assert_count = sum(1 for event in events if event.op == "assert")
        retract_count = sum(1 for event in events if event.op == "retract")
        introduced = chronological[0]
        latest = events[0]
        return {
            "event_count": len(events),
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
            "events": [event.to_dict() for event in events],
        }


def _governance_rule_model(record: GovernanceRuleRecord) -> GovernanceRule:
    return GovernanceRule.from_dict(record.to_dict())


@dataclass(slots=True)
class SQLiteGovernanceBackend:
    versions: SQLiteVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def list_rules(self) -> list[GovernanceRuleRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM governance_rules ORDER BY name").fetchall()
        return [
            GovernanceRuleRecord.from_governance_rule(json.loads(row["payload"]), tenant_id=self.tenant_id)
            for row in rows
        ]

    def upsert_rule(self, rule: GovernanceRuleRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO governance_rules(name, payload) VALUES(?, ?)
                ON CONFLICT(name) DO UPDATE SET payload = excluded.payload
                """,
                (rule.name, json.dumps(rule.to_dict(), ensure_ascii=False)),
            )

    def remove_rule(self, name: str) -> bool:
        with self._connect() as conn:
            before = conn.total_changes
            conn.execute("DELETE FROM governance_rules WHERE name = ?", (name,))
            return conn.total_changes > before

    def _approval_reasons(
        self,
        rule: GovernanceRule,
        *,
        current_graph: CortexGraph | None,
        baseline_graph: CortexGraph | None,
    ) -> list[str]:
        if current_graph is None:
            return []
        reasons: list[str] = []
        changed_nodes = list(current_graph.nodes.values())
        semantic_changes: list[dict[str, Any]] = []
        if baseline_graph is not None:
            structural = diff_graphs(baseline_graph, current_graph)
            touched_ids = (
                {item["id"] for item in structural.get("added_nodes", [])}
                | {item["id"] for item in structural.get("modified_nodes", [])}
                | {item["id"] for item in structural.get("removed_nodes", [])}
            )
            changed_nodes = [current_graph.nodes[node_id] for node_id in touched_ids if node_id in current_graph.nodes]
            semantic_changes = semantic_diff_graphs(baseline_graph, current_graph)["changes"]
        if rule.approval_below_confidence is not None:
            risky = sorted(
                [node for node in changed_nodes if node.confidence < float(rule.approval_below_confidence)],
                key=lambda node: node.confidence,
            )
            if risky:
                preview = ", ".join(f"{node.label} ({node.confidence:.2f})" for node in risky[:5])
                reasons.append(f"Low-confidence changes below {float(rule.approval_below_confidence):.2f}: {preview}")
        if rule.approval_tags:
            matched = [node.label for node in changed_nodes if any(tag in set(node.tags) for tag in rule.approval_tags)]
            if matched:
                reasons.append("Protected tag changes: " + ", ".join(sorted(dict.fromkeys(matched))[:10]))
        if rule.approval_change_types and semantic_changes:
            matched = [change for change in semantic_changes if change.get("type") in set(rule.approval_change_types)]
            if matched:
                preview = ", ".join(sorted(dict.fromkeys(change["type"] for change in matched)))
                reasons.append(f"Semantic changes requiring review: {preview}")
        return reasons

    def authorize(
        self,
        actor: str,
        action: str,
        namespace: str,
        *,
        current_graph: CortexGraph | None = None,
        baseline_graph: CortexGraph | None = None,
    ) -> GovernanceDecisionRecord:
        rules = [_governance_rule_model(rule) for rule in self.list_rules()]
        if not rules:
            return GovernanceDecisionRecord(
                tenant_id=self.tenant_id,
                namespace=namespace,
                allowed=True,
                require_approval=False,
                actor=actor,
                action=action,
            )
        matching = [rule for rule in rules if rule.matches(actor, action, namespace)]
        if not matching:
            return GovernanceDecisionRecord(
                tenant_id=self.tenant_id,
                namespace=namespace,
                allowed=False,
                require_approval=False,
                actor=actor,
                action=action,
                reasons=["No matching governance rule allows this action."],
            )
        deny_rules = [rule for rule in matching if rule.effect == "deny"]
        if deny_rules:
            return GovernanceDecisionRecord(
                tenant_id=self.tenant_id,
                namespace=namespace,
                allowed=False,
                require_approval=False,
                actor=actor,
                action=action,
                reasons=[f"Blocked by governance rule '{rule.name}'." for rule in deny_rules],
                matched_rules=[rule.name for rule in matching],
            )
        allow_rules = [rule for rule in matching if rule.effect == "allow"]
        require_approval = False
        reasons: list[str] = []
        for rule in allow_rules:
            if rule.require_approval:
                require_approval = True
                reasons.append(f"Rule '{rule.name}' requires explicit approval.")
            reasons.extend(self._approval_reasons(rule, current_graph=current_graph, baseline_graph=baseline_graph))
        if reasons:
            require_approval = True
        return GovernanceDecisionRecord(
            tenant_id=self.tenant_id,
            namespace=namespace,
            allowed=True,
            require_approval=require_approval,
            actor=actor,
            action=action,
            reasons=reasons,
            matched_rules=[rule.name for rule in matching],
        )


@dataclass(slots=True)
class SQLiteRemoteBackend:
    versions: SQLiteVersionBackend
    tenant_id: str = DEFAULT_TENANT_ID

    def _connect(self) -> sqlite3.Connection:
        return self.versions._connect()

    def list_remotes(self) -> list[RemoteRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM remotes ORDER BY name").fetchall()
        remotes: list[RemoteRecord] = []
        for row in rows:
            payload = json.loads(row["payload"])
            record = RemoteRecord.from_memory_remote(payload, tenant_id=self.tenant_id)
            if not record.resolved_store_path:
                record = RemoteRecord(
                    tenant_id=record.tenant_id,
                    name=record.name,
                    path=record.path,
                    resolved_store_path=str(_normalize_store_path(record.path)),
                    default_branch=record.default_branch,
                    trusted_did=record.trusted_did,
                    trusted_public_key_b64=record.trusted_public_key_b64,
                    allowed_namespaces=list(record.allowed_namespaces),
                )
            remotes.append(record)
        return remotes

    def add_remote(self, remote: RemoteRecord) -> None:
        prepared = prepare_remote_fields(remote)
        stored_remote = RemoteRecord(
            tenant_id=remote.tenant_id,
            name=remote.name,
            path=remote.path,
            resolved_store_path=prepared["resolved_store_path"],
            default_branch=remote.default_branch,
            trusted_did=prepared["trusted_did"],
            trusted_public_key_b64=prepared["trusted_public_key_b64"],
            allowed_namespaces=list(prepared["allowed_namespaces"]),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO remotes(name, payload) VALUES(?, ?)
                ON CONFLICT(name) DO UPDATE SET payload = excluded.payload
                """,
                (stored_remote.name, json.dumps(stored_remote.to_dict(), ensure_ascii=False)),
            )

    def remove_remote(self, name: str) -> bool:
        with self._connect() as conn:
            before = conn.total_changes
            conn.execute("DELETE FROM remotes WHERE name = ?", (name,))
            return conn.total_changes > before

    def _require_remote(self, name: str) -> RemoteRecord:
        for remote in self.list_remotes():
            if remote.name == name:
                if not remote.trusted_did or not remote.trusted_public_key_b64 or not remote.allowed_namespaces:
                    self.add_remote(remote)
                    return next(item for item in self.list_remotes() if item.name == name)
                return remote
        raise ValueError(f"Unknown remote: {name}")

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
    def storage_backend(self) -> "SQLiteStorageBackend":
        return SQLiteStorageBackend(self.versions.store_dir, tenant_id=self.tenant_id)


@dataclass(slots=True)
class SQLiteStorageBackend:
    store_dir: Path
    tenant_id: str = DEFAULT_TENANT_ID
    versions: SQLiteVersionBackend = field(init=False)
    claims: SQLiteClaimBackend = field(init=False)
    governance: SQLiteGovernanceBackend = field(init=False)
    remotes: SQLiteRemoteBackend = field(init=False)
    indexing: SQLiteIndexBackend = field(init=False)
    maintenance: SQLiteMaintenanceBackend = field(init=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        versions = SQLiteVersionBackend(self.store_dir, tenant_id=self.tenant_id)
        self.versions = versions
        self.indexing = SQLiteIndexBackend(versions)
        versions.index_backend = self.indexing
        self.claims = SQLiteClaimBackend(versions, tenant_id=self.tenant_id)
        self.governance = SQLiteGovernanceBackend(versions, tenant_id=self.tenant_id)
        self.remotes = SQLiteRemoteBackend(versions, tenant_id=self.tenant_id)
        self.maintenance = SQLiteMaintenanceBackend(versions)


def build_sqlite_backend(
    store_dir: str | Path,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> SQLiteStorageBackend:
    return SQLiteStorageBackend(Path(store_dir), tenant_id=tenant_id)


__all__ = [
    "DEFAULT_SQLITE_FILENAME",
    "SQLiteClaimBackend",
    "SQLiteGovernanceBackend",
    "SQLiteMaintenanceBackend",
    "SQLiteRemoteBackend",
    "SQLiteStorageBackend",
    "SQLiteVersionBackend",
    "build_sqlite_backend",
    "sqlite_db_path",
]
