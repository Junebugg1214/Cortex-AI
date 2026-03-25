from __future__ import annotations

from typing import Any

from cortex.schemas.memory_v1 import (
    BranchRecord,
    ClaimRecord,
    CommitRecord,
    GovernanceDecisionRecord,
    GovernanceRuleRecord,
    MemoryEdgeRecord,
    MemoryGraphRecord,
    MemoryNodeRecord,
    RemoteRecord,
)
from cortex.upai.schemas import validate

MEMORY_NODE_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "namespace", "id", "label", "tags", "confidence"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "namespace": {"type": "string", "minLength": 1},
        "id": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "properties": {"type": "object"},
        "brief": {"type": "string"},
        "full_description": {"type": "string"},
        "mention_count": {"type": "integer", "minimum": 0},
        "provenance": {"type": "array", "items": {"type": "object"}},
        "snapshots": {"type": "array", "items": {"type": "object"}},
    },
}

MEMORY_EDGE_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "namespace", "id", "source_id", "target_id", "relation"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "namespace": {"type": "string", "minLength": 1},
        "id": {"type": "string", "minLength": 1},
        "source_id": {"type": "string", "minLength": 1},
        "target_id": {"type": "string", "minLength": 1},
        "relation": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "properties": {"type": "object"},
        "qualifiers": {"type": "object"},
        "provenance": {"type": "array", "items": {"type": "object"}},
    },
}

MEMORY_GRAPH_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "namespace", "meta", "nodes", "edges"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "namespace": {"type": "string", "minLength": 1},
        "meta": {"type": "object"},
        "nodes": {"type": "array", "items": MEMORY_NODE_RECORD_SCHEMA},
        "edges": {"type": "array", "items": MEMORY_EDGE_RECORD_SCHEMA},
    },
}

COMMIT_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "namespace", "version_id", "timestamp", "source", "message"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "namespace": {"type": "string", "minLength": 1},
        "version_id": {"type": "string", "minLength": 1},
        "parent_id": {"type": ["string", "null"]},
        "merge_parent_ids": {"type": "array", "items": {"type": "string"}},
        "timestamp": {"type": "string", "minLength": 1},
        "source": {"type": "string", "minLength": 1},
        "message": {"type": "string"},
        "graph_hash": {"type": "string"},
        "node_count": {"type": "integer", "minimum": 0},
        "edge_count": {"type": "integer", "minimum": 0},
        "signature": {"type": ["string", "null"]},
    },
}

BRANCH_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "name", "current"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "head": {"type": ["string", "null"]},
        "current": {"type": "boolean"},
    },
}

CLAIM_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "namespace", "event_id", "claim_id", "op", "node_id", "label"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "namespace": {"type": "string", "minLength": 1},
        "event_id": {"type": "string", "minLength": 1},
        "claim_id": {"type": "string", "minLength": 1},
        "op": {"type": "string", "minLength": 1},
        "node_id": {"type": "string", "minLength": 1},
        "canonical_id": {"type": "string"},
        "label": {"type": "string", "minLength": 1},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "source": {"type": "string"},
        "method": {"type": "string"},
        "timestamp": {"type": "string"},
        "version_id": {"type": "string"},
        "metadata": {"type": "object"},
    },
}

GOVERNANCE_RULE_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "name", "effect", "actor_pattern", "actions", "namespaces"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "effect": {"type": "string", "minLength": 1},
        "actor_pattern": {"type": "string", "minLength": 1},
        "actions": {"type": "array", "items": {"type": "string"}},
        "namespaces": {"type": "array", "items": {"type": "string"}},
        "require_approval": {"type": "boolean"},
        "approval_below_confidence": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
        "approval_tags": {"type": "array", "items": {"type": "string"}},
        "approval_change_types": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
    },
}

GOVERNANCE_DECISION_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "namespace", "allowed", "require_approval", "actor", "action"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "namespace": {"type": "string", "minLength": 1},
        "allowed": {"type": "boolean"},
        "require_approval": {"type": "boolean"},
        "actor": {"type": "string", "minLength": 1},
        "action": {"type": "string", "minLength": 1},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "matched_rules": {"type": "array", "items": {"type": "string"}},
    },
}

REMOTE_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tenant_id", "name", "path", "default_branch"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "path": {"type": "string", "minLength": 1},
        "resolved_store_path": {"type": "string"},
        "default_branch": {"type": "string", "minLength": 1},
    },
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "memory_node": MEMORY_NODE_RECORD_SCHEMA,
    "memory_edge": MEMORY_EDGE_RECORD_SCHEMA,
    "memory_graph": MEMORY_GRAPH_RECORD_SCHEMA,
    "commit": COMMIT_RECORD_SCHEMA,
    "branch": BRANCH_RECORD_SCHEMA,
    "claim": CLAIM_RECORD_SCHEMA,
    "governance_rule": GOVERNANCE_RULE_RECORD_SCHEMA,
    "governance_decision": GOVERNANCE_DECISION_RECORD_SCHEMA,
    "remote": REMOTE_RECORD_SCHEMA,
}

MODEL_SCHEMA_NAMES: dict[type[Any], str] = {
    MemoryNodeRecord: "memory_node",
    MemoryEdgeRecord: "memory_edge",
    MemoryGraphRecord: "memory_graph",
    CommitRecord: "commit",
    BranchRecord: "branch",
    ClaimRecord: "claim",
    GovernanceRuleRecord: "governance_rule",
    GovernanceDecisionRecord: "governance_decision",
    RemoteRecord: "remote",
}


def validate_record(data: dict[str, Any], schema_name: str) -> list[str]:
    schema = SCHEMAS[schema_name]
    return validate(data, schema)


def validate_model(model: Any, schema_name: str | None = None) -> list[str]:
    payload = model.to_dict() if hasattr(model, "to_dict") else dict(model)
    resolved_name = schema_name or MODEL_SCHEMA_NAMES[type(model)]
    return validate_record(payload, resolved_name)


__all__ = ["SCHEMAS", "validate_model", "validate_record"]
