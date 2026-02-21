"""
TypedDict definitions for CaaS API resources.

These mirror the TypeScript interfaces in sdk/typescript/src/types.ts.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ServerInfo(TypedDict, total=False):
    name: str
    version: str
    did: str
    endpoints: dict[str, str]


class HealthCheck(TypedDict, total=False):
    status: str
    timestamp: str


class ContextNode(TypedDict, total=False):
    id: str
    label: str
    tags: list[str]
    confidence: float
    brief: str
    full_description: str
    properties: dict[str, Any]


class ContextEdge(TypedDict, total=False):
    source: str
    target: str
    relation: str
    weight: float


class GraphStats(TypedDict, total=False):
    node_count: int
    edge_count: int
    avg_degree: float
    tag_distribution: dict[str, int]


class Grant(TypedDict, total=False):
    grant_id: str
    audience: str
    policy: str
    scopes: list[str]
    created_at: str
    expires_at: str
    revoked: bool
    token: str


class Webhook(TypedDict, total=False):
    webhook_id: str
    url: str
    events: list[str]
    created_at: str


class Policy(TypedDict, total=False):
    name: str
    include_tags: list[str]
    exclude_tags: list[str]
    min_confidence: float
    redact_properties: list[str]
    max_nodes: int
    builtin: bool


class VersionSnapshot(TypedDict, total=False):
    version_id: str
    timestamp: str
    message: str
    source: str
    node_count: int
    edge_count: int
    parent_id: str
    signature: str


class VersionDiff(TypedDict, total=False):
    version_a: str
    version_b: str
    added_nodes: list[str]
    removed_nodes: list[str]
    modified_nodes: list[str]
    added_edges: list[str]
    removed_edges: list[str]
