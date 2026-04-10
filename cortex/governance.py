"""
Governance and access control for Git-for-AI-Memory workflows.

Rules define which actors can read, write, branch, merge, push, and pull
against memory namespaces, plus when human approval is required.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cortex.atomic_io import atomic_write_text, locked_path
from cortex.graph import CortexGraph, diff_graphs
from cortex.semantic_diff import semantic_diff_graphs

GOVERNANCE_ACTIONS = frozenset({"read", "write", "branch", "merge", "rollback", "push", "pull"})


@dataclass
class GovernanceRule:
    name: str
    effect: str
    actor_pattern: str = "*"
    actions: list[str] = field(default_factory=lambda: ["*"])
    namespaces: list[str] = field(default_factory=lambda: ["*"])
    require_approval: bool = False
    approval_below_confidence: float | None = None
    approval_tags: list[str] = field(default_factory=list)
    approval_change_types: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "effect": self.effect,
            "actor_pattern": self.actor_pattern,
            "actions": list(self.actions),
            "namespaces": list(self.namespaces),
            "require_approval": self.require_approval,
            "approval_below_confidence": self.approval_below_confidence,
            "approval_tags": list(self.approval_tags),
            "approval_change_types": list(self.approval_change_types),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GovernanceRule":
        return cls(
            name=data["name"],
            effect=data.get("effect", "allow"),
            actor_pattern=data.get("actor_pattern", "*"),
            actions=list(data.get("actions", ["*"])),
            namespaces=list(data.get("namespaces", ["*"])),
            require_approval=bool(data.get("require_approval", False)),
            approval_below_confidence=data.get("approval_below_confidence"),
            approval_tags=list(data.get("approval_tags", [])),
            approval_change_types=list(data.get("approval_change_types", [])),
            description=data.get("description", ""),
        )

    def matches(self, actor: str, action: str, namespace: str) -> bool:
        action_match = "*" in self.actions or action in self.actions
        namespace_match = any(fnmatch.fnmatch(namespace, pattern) for pattern in (self.namespaces or ["*"]))
        actor_match = fnmatch.fnmatch(actor, self.actor_pattern or "*")
        return actor_match and action_match and namespace_match


@dataclass
class GovernanceDecision:
    allowed: bool
    require_approval: bool
    actor: str
    action: str
    namespace: str
    reasons: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "require_approval": self.require_approval,
            "actor": self.actor,
            "action": self.action,
            "namespace": self.namespace,
            "reasons": list(self.reasons),
            "matched_rules": list(self.matched_rules),
        }


class GovernanceStore:
    def __init__(self, store_dir: str | Path) -> None:
        self.store_dir = Path(store_dir)
        self.path = self.store_dir / "governance.json"

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"rules": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save_payload(self, payload: dict[str, Any]) -> None:
        atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def list_rules(self) -> list[GovernanceRule]:
        payload = self._load_payload()
        return [GovernanceRule.from_dict(item) for item in payload.get("rules", [])]

    def upsert_rule(self, rule: GovernanceRule) -> None:
        with locked_path(self.store_dir):
            payload = self._load_payload()
            rules = [item for item in payload.get("rules", []) if item.get("name") != rule.name]
            rules.append(rule.to_dict())
            payload["rules"] = sorted(rules, key=lambda item: item["name"])
            self._save_payload(payload)

    def remove_rule(self, name: str) -> bool:
        with locked_path(self.store_dir):
            payload = self._load_payload()
            before = len(payload.get("rules", []))
            payload["rules"] = [item for item in payload.get("rules", []) if item.get("name") != name]
            if len(payload["rules"]) == before:
                return False
            self._save_payload(payload)
            return True

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
    ) -> GovernanceDecision:
        rules = self.list_rules()
        if not rules:
            return GovernanceDecision(
                allowed=True,
                require_approval=False,
                actor=actor,
                action=action,
                namespace=namespace,
            )

        matching = [rule for rule in rules if rule.matches(actor, action, namespace)]
        if not matching:
            return GovernanceDecision(
                allowed=False,
                require_approval=False,
                actor=actor,
                action=action,
                namespace=namespace,
                reasons=["No matching governance rule allows this action."],
            )

        deny_rules = [rule for rule in matching if rule.effect == "deny"]
        if deny_rules:
            return GovernanceDecision(
                allowed=False,
                require_approval=False,
                actor=actor,
                action=action,
                namespace=namespace,
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

        return GovernanceDecision(
            allowed=True,
            require_approval=require_approval,
            actor=actor,
            action=action,
            namespace=namespace,
            reasons=reasons,
            matched_rules=[rule.name for rule in matching],
        )
