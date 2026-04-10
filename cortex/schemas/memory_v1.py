from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from cortex.namespaces import normalize_acl_namespaces

DEFAULT_TENANT_ID = "default"
DEFAULT_NAMESPACE = "main"


class _RecordMixin:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryNodeRecord(_RecordMixin):
    id: str
    label: str
    tags: list[str] = field(default_factory=list)
    tenant_id: str = DEFAULT_TENANT_ID
    namespace: str = DEFAULT_NAMESPACE
    aliases: list[str] = field(default_factory=list)
    confidence: float = 0.0
    properties: dict[str, Any] = field(default_factory=dict)
    brief: str = ""
    full_description: str = ""
    mention_count: int = 1
    extraction_method: str = "mentioned"
    metrics: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    source_quotes: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    valid_from: str = ""
    valid_to: str = ""
    status: str = ""
    canonical_id: str = ""
    provenance: list[dict[str, Any]] = field(default_factory=list)
    relationship_type: str = ""
    snapshots: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_node(
        cls,
        node: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> "MemoryNodeRecord":
        payload = node.to_dict() if hasattr(node, "to_dict") else dict(node)
        return cls(
            tenant_id=tenant_id,
            namespace=namespace,
            id=payload["id"],
            label=payload["label"],
            tags=list(payload.get("tags", [])),
            aliases=list(payload.get("aliases", [])),
            confidence=float(payload.get("confidence", 0.0)),
            properties=dict(payload.get("properties", {})),
            brief=payload.get("brief", ""),
            full_description=payload.get("full_description", ""),
            mention_count=int(payload.get("mention_count", 1)),
            extraction_method=payload.get("extraction_method", "mentioned"),
            metrics=list(payload.get("metrics", [])),
            timeline=list(payload.get("timeline", [])),
            source_quotes=list(payload.get("source_quotes", [])),
            first_seen=payload.get("first_seen", ""),
            last_seen=payload.get("last_seen", ""),
            valid_from=payload.get("valid_from", ""),
            valid_to=payload.get("valid_to", ""),
            status=payload.get("status", ""),
            canonical_id=payload.get("canonical_id", ""),
            provenance=[dict(item) for item in payload.get("provenance", [])],
            relationship_type=payload.get("relationship_type", ""),
            snapshots=[dict(item) for item in payload.get("snapshots", [])],
        )


@dataclass(slots=True)
class MemoryEdgeRecord(_RecordMixin):
    id: str
    source_id: str
    target_id: str
    relation: str
    tenant_id: str = DEFAULT_TENANT_ID
    namespace: str = DEFAULT_NAMESPACE
    confidence: float = 0.0
    properties: dict[str, Any] = field(default_factory=dict)
    qualifiers: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""

    @classmethod
    def from_edge(
        cls,
        edge: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> "MemoryEdgeRecord":
        payload = edge.to_dict() if hasattr(edge, "to_dict") else dict(edge)
        return cls(
            tenant_id=tenant_id,
            namespace=namespace,
            id=payload["id"],
            source_id=payload["source_id"],
            target_id=payload["target_id"],
            relation=payload["relation"],
            confidence=float(payload.get("confidence", 0.0)),
            properties=dict(payload.get("properties", {})),
            qualifiers=dict(payload.get("qualifiers", {})),
            provenance=[dict(item) for item in payload.get("provenance", [])],
            first_seen=payload.get("first_seen", ""),
            last_seen=payload.get("last_seen", ""),
        )


@dataclass(slots=True)
class MemoryGraphRecord(_RecordMixin):
    tenant_id: str = DEFAULT_TENANT_ID
    namespace: str = DEFAULT_NAMESPACE
    meta: dict[str, Any] = field(default_factory=dict)
    nodes: list[MemoryNodeRecord] = field(default_factory=list)
    edges: list[MemoryEdgeRecord] = field(default_factory=list)

    @classmethod
    def from_graph(
        cls,
        graph: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> "MemoryGraphRecord":
        return cls(
            tenant_id=tenant_id,
            namespace=namespace,
            meta=dict(getattr(graph, "meta", {}) or {}),
            nodes=[
                MemoryNodeRecord.from_node(node, tenant_id=tenant_id, namespace=namespace)
                for node in getattr(graph, "nodes", {}).values()
            ],
            edges=[
                MemoryEdgeRecord.from_edge(edge, tenant_id=tenant_id, namespace=namespace)
                for edge in getattr(graph, "edges", {}).values()
            ],
        )


@dataclass(slots=True)
class CommitRecord(_RecordMixin):
    version_id: str
    tenant_id: str = DEFAULT_TENANT_ID
    namespace: str = DEFAULT_NAMESPACE
    parent_id: str | None = None
    merge_parent_ids: list[str] = field(default_factory=list)
    timestamp: str = ""
    source: str = ""
    message: str = ""
    graph_hash: str = ""
    node_count: int = 0
    edge_count: int = 0
    signature: str | None = None

    @classmethod
    def from_context_version(
        cls,
        version: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        namespace: str | None = None,
    ) -> "CommitRecord":
        payload = version.to_dict() if hasattr(version, "to_dict") else dict(version)
        return cls(
            tenant_id=tenant_id,
            namespace=namespace or payload.get("branch") or DEFAULT_NAMESPACE,
            version_id=payload["version_id"],
            parent_id=payload.get("parent_id"),
            merge_parent_ids=list(payload.get("merge_parent_ids", [])),
            timestamp=payload.get("timestamp", ""),
            source=payload.get("source", ""),
            message=payload.get("message", ""),
            graph_hash=payload.get("graph_hash", ""),
            node_count=int(payload.get("node_count", 0)),
            edge_count=int(payload.get("edge_count", 0)),
            signature=payload.get("signature"),
        )


@dataclass(slots=True)
class BranchRecord(_RecordMixin):
    name: str
    tenant_id: str = DEFAULT_TENANT_ID
    head: str | None = None
    current: bool = False

    @classmethod
    def from_branch_payload(
        cls,
        branch: dict[str, Any],
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> "BranchRecord":
        return cls(
            tenant_id=tenant_id,
            name=branch["name"],
            head=branch.get("head"),
            current=bool(branch.get("current", False)),
        )


@dataclass(slots=True)
class ClaimRecord(_RecordMixin):
    event_id: str
    claim_id: str
    op: str
    node_id: str
    label: str
    tenant_id: str = DEFAULT_TENANT_ID
    namespace: str = DEFAULT_NAMESPACE
    canonical_id: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = ""
    valid_from: str = ""
    valid_to: str = ""
    source: str = ""
    method: str = ""
    timestamp: str = ""
    version_id: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_claim_event(
        cls,
        event: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> "ClaimRecord":
        payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        return cls(
            tenant_id=tenant_id,
            namespace=namespace,
            event_id=payload["event_id"],
            claim_id=payload["claim_id"],
            op=payload["op"],
            node_id=payload["node_id"],
            canonical_id=payload.get("canonical_id", ""),
            label=payload["label"],
            aliases=list(payload.get("aliases", [])),
            tags=list(payload.get("tags", [])),
            confidence=float(payload.get("confidence", 0.0)),
            status=payload.get("status", ""),
            valid_from=payload.get("valid_from", ""),
            valid_to=payload.get("valid_to", ""),
            source=payload.get("source", ""),
            method=payload.get("method", ""),
            timestamp=payload.get("timestamp", ""),
            version_id=payload.get("version_id", ""),
            message=payload.get("message", ""),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class GovernanceRuleRecord(_RecordMixin):
    name: str
    effect: str
    tenant_id: str = DEFAULT_TENANT_ID
    actor_pattern: str = "*"
    actions: list[str] = field(default_factory=lambda: ["*"])
    namespaces: list[str] = field(default_factory=lambda: [DEFAULT_NAMESPACE])
    require_approval: bool = False
    approval_below_confidence: float | None = None
    approval_tags: list[str] = field(default_factory=list)
    approval_change_types: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_governance_rule(
        cls,
        rule: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> "GovernanceRuleRecord":
        payload = rule.to_dict() if hasattr(rule, "to_dict") else dict(rule)
        return cls(
            tenant_id=tenant_id,
            name=payload["name"],
            effect=payload.get("effect", "allow"),
            actor_pattern=payload.get("actor_pattern", "*"),
            actions=list(payload.get("actions", ["*"])),
            namespaces=list(payload.get("namespaces", [DEFAULT_NAMESPACE])),
            require_approval=bool(payload.get("require_approval", False)),
            approval_below_confidence=payload.get("approval_below_confidence"),
            approval_tags=list(payload.get("approval_tags", [])),
            approval_change_types=list(payload.get("approval_change_types", [])),
            description=payload.get("description", ""),
        )


@dataclass(slots=True)
class GovernanceDecisionRecord(_RecordMixin):
    allowed: bool
    require_approval: bool
    actor: str
    action: str
    namespace: str
    tenant_id: str = DEFAULT_TENANT_ID
    reasons: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)

    @classmethod
    def from_governance_decision(
        cls,
        decision: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> "GovernanceDecisionRecord":
        payload = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
        return cls(
            tenant_id=tenant_id,
            allowed=bool(payload.get("allowed", False)),
            require_approval=bool(payload.get("require_approval", False)),
            actor=payload.get("actor", ""),
            action=payload.get("action", ""),
            namespace=payload.get("namespace", DEFAULT_NAMESPACE),
            reasons=list(payload.get("reasons", [])),
            matched_rules=list(payload.get("matched_rules", [])),
        )


@dataclass(slots=True)
class RemoteRecord(_RecordMixin):
    name: str
    path: str
    tenant_id: str = DEFAULT_TENANT_ID
    resolved_store_path: str = ""
    default_branch: str = DEFAULT_NAMESPACE
    trusted_did: str = ""
    trusted_public_key_b64: str = ""
    allowed_namespaces: list[str] = field(default_factory=list)

    @classmethod
    def from_memory_remote(
        cls,
        remote: Any,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> "RemoteRecord":
        payload = remote.to_dict() if hasattr(remote, "to_dict") else dict(remote)
        resolved_store_path = payload.get("resolved_store_path")
        if not resolved_store_path and hasattr(remote, "store_path"):
            resolved_store_path = str(remote.store_path)
        return cls(
            tenant_id=tenant_id,
            name=payload["name"],
            path=payload["path"],
            resolved_store_path=resolved_store_path or "",
            default_branch=payload.get("default_branch", DEFAULT_NAMESPACE),
            trusted_did=payload.get("trusted_did", ""),
            trusted_public_key_b64=payload.get("trusted_public_key_b64", ""),
            allowed_namespaces=list(
                normalize_acl_namespaces(
                    payload.get("allowed_namespaces") or [payload.get("default_branch", DEFAULT_NAMESPACE)]
                )
            ),
        )


__all__ = [
    "DEFAULT_NAMESPACE",
    "DEFAULT_TENANT_ID",
    "BranchRecord",
    "ClaimRecord",
    "CommitRecord",
    "GovernanceDecisionRecord",
    "GovernanceRuleRecord",
    "MemoryEdgeRecord",
    "MemoryGraphRecord",
    "MemoryNodeRecord",
    "RemoteRecord",
]
