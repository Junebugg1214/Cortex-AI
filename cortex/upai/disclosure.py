"""
Selective Disclosure — Filter graph nodes by policy before export.

Policies control which nodes are visible to a given platform or audience.
"""

from __future__ import annotations

import copy
import re
import threading
from dataclasses import dataclass
from typing import Any

from cortex.graph import CortexGraph


@dataclass
class DisclosurePolicy:
    name: str                     # "professional", "technical", "full", "minimal"
    include_tags: list[str]       # tags to include (empty = all)
    exclude_tags: list[str]       # tags to exclude
    min_confidence: float         # confidence floor
    redact_properties: list[str]  # property keys to strip
    max_nodes: int = 0            # 0 = unlimited


BUILTIN_POLICIES = {
    "full": DisclosurePolicy(
        name="full",
        include_tags=[],
        exclude_tags=[],
        min_confidence=0.0,
        redact_properties=[],
    ),
    "professional": DisclosurePolicy(
        name="professional",
        include_tags=[
            "identity", "professional_context", "business_context",
            "technical_expertise", "active_priorities",
            "work_history", "education_history",
        ],
        exclude_tags=["negations", "correction_history"],
        min_confidence=0.6,
        redact_properties=[],
    ),
    "technical": DisclosurePolicy(
        name="technical",
        include_tags=[
            "technical_expertise", "domain_knowledge", "active_priorities",
        ],
        exclude_tags=[],
        min_confidence=0.5,
        redact_properties=[],
    ),
    "minimal": DisclosurePolicy(
        name="minimal",
        include_tags=["identity", "communication_preferences"],
        exclude_tags=[],
        min_confidence=0.8,
        redact_properties=[],
    ),
}


_POLICY_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$")


class PolicyRegistry:
    """Thread-safe registry that wraps built-in + custom disclosure policies."""

    def __init__(self, store: Any | None = None) -> None:
        self._custom: dict[str, DisclosurePolicy] = {}
        self._lock = threading.Lock()
        self._store = store
        if store is not None:
            for p in store.list_all():
                self._custom[p.name] = p

    @staticmethod
    def _validate_name(name: str) -> bool:
        return bool(_POLICY_NAME_RE.match(name))

    def is_builtin(self, name: str) -> bool:
        return name in BUILTIN_POLICIES

    def get(self, name: str) -> DisclosurePolicy | None:
        if name in BUILTIN_POLICIES:
            return BUILTIN_POLICIES[name]
        with self._lock:
            return self._custom.get(name)

    def list_all(self) -> list[DisclosurePolicy]:
        with self._lock:
            return list(BUILTIN_POLICIES.values()) + list(self._custom.values())

    def register(self, policy: DisclosurePolicy) -> None:
        if not self._validate_name(policy.name):
            raise ValueError(f"Invalid policy name: {policy.name}")
        if self.is_builtin(policy.name):
            raise ValueError(f"Cannot override built-in policy: {policy.name}")
        with self._lock:
            self._custom[policy.name] = policy
            if self._store is not None:
                self._store.add(policy)

    def update(self, name: str, policy: DisclosurePolicy) -> bool:
        if self.is_builtin(name):
            raise ValueError(f"Cannot modify built-in policy: {name}")
        with self._lock:
            if name not in self._custom:
                return False
            # If name changed, remove old
            if policy.name != name:
                del self._custom[name]
                if self._store is not None:
                    self._store.delete(name)
            self._custom[policy.name] = policy
            if self._store is not None:
                self._store.update(policy.name, policy)
            return True

    def delete(self, name: str) -> bool:
        if self.is_builtin(name):
            raise ValueError(f"Cannot delete built-in policy: {name}")
        with self._lock:
            if name not in self._custom:
                return False
            del self._custom[name]
            if self._store is not None:
                self._store.delete(name)
            return True


def apply_disclosure(graph: CortexGraph, policy: DisclosurePolicy) -> CortexGraph:
    """Return a filtered deep copy of the graph based on disclosure policy.

    - Filter nodes by include_tags/exclude_tags/min_confidence
    - Strip redact_properties from node.properties
    - Cap at max_nodes (highest confidence first)
    - Remove edges where either endpoint was filtered out
    """
    # Filter metadata for non-full policies (#5: prevent metadata leakage)
    is_full = policy.name == "full"
    if is_full:
        filtered_meta = copy.deepcopy(graph.meta)
    else:
        # Only preserve safe metadata keys
        _SAFE_META_KEYS = {"schema_version", "generated_at"}
        filtered_meta = {k: v for k, v in graph.meta.items() if k in _SAFE_META_KEYS}

    result = CortexGraph(
        schema_version=graph.schema_version,
        meta=filtered_meta,
    )

    # Collect candidate nodes
    candidates = []
    for nid, node in graph.nodes.items():
        # Confidence filter
        if node.confidence < policy.min_confidence:
            continue

        # Exclude tags filter
        if policy.exclude_tags and any(t in policy.exclude_tags for t in node.tags):
            continue

        # Include tags filter (empty = include all)
        if policy.include_tags:
            if not any(t in policy.include_tags for t in node.tags):
                continue

        candidates.append((nid, node))

    # Sort by confidence descending for max_nodes cap
    candidates.sort(key=lambda x: x[1].confidence, reverse=True)

    # Cap at max_nodes
    if policy.max_nodes > 0:
        candidates = candidates[:policy.max_nodes]

    # Build result graph
    included_ids = set()
    for nid, node in candidates:
        node_copy = copy.deepcopy(node)

        # Redact properties
        for prop_key in policy.redact_properties:
            node_copy.properties.pop(prop_key, None)

        # Strip source_quotes and full_description for non-full policies (#17)
        if not is_full:
            node_copy.source_quotes = []
            node_copy.full_description = ""

        # Filter snapshots through disclosure policy (#4)
        if not is_full and hasattr(node_copy, "snapshots"):
            filtered_snaps = []
            for snap in node_copy.snapshots:
                snap_tags = snap.get("tags", [])
                if policy.exclude_tags and any(t in policy.exclude_tags for t in snap_tags):
                    continue
                if policy.include_tags and not any(t in policy.include_tags for t in snap_tags):
                    continue
                # Strip redact_properties from snapshot if present
                for prop_key in policy.redact_properties:
                    snap.pop(prop_key, None)
                filtered_snaps.append(snap)
            node_copy.snapshots = filtered_snaps

        result.nodes[nid] = node_copy
        included_ids.add(nid)

    # Include edges where both endpoints exist, with property redaction (#3)
    for eid, edge in graph.edges.items():
        if edge.source_id in included_ids and edge.target_id in included_ids:
            edge_copy = copy.deepcopy(edge)
            for prop_key in policy.redact_properties:
                edge_copy.properties.pop(prop_key, None)
            result.edges[eid] = edge_copy

    return result
