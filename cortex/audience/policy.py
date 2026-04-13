"""Audience policy engine for first-class Mind compilation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from cortex.atomic_io import atomic_write_json, locked_path
from cortex.graph import CortexGraph
from cortex.minds import load_mind_manifest, mind_path


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def audience_policy_path(store_dir: Path, mind_id: str) -> Path:
    """Return the policy storage path for a Mind."""
    return mind_path(store_dir, mind_id) / "audiences.json"


def audience_log_path(store_dir: Path, mind_id: str) -> Path:
    """Return the compilation log path for a Mind."""
    return mind_path(store_dir, mind_id) / "audience_logs.jsonl"


class AudiencePolicyError(ValueError):
    """Base class for audience policy failures."""


class UnknownAudiencePolicyError(AudiencePolicyError):
    """Raised when a requested audience policy does not exist."""


@dataclass(slots=True)
class AudiencePolicy:
    """Audience-scoped disclosure, formatting, and delivery policy."""

    audience_id: str
    display_name: str
    allowed_node_types: list[str]
    blocked_node_types: list[str]
    allowed_claim_confidences: tuple[float, float]
    redact_fields: list[str]
    output_format: Literal["brief", "pack", "cv", "report", "raw"]
    delivery: Literal["file", "webhook", "stdout"]
    delivery_target: str | None
    include_provenance: bool
    include_contested: bool

    def validate(self) -> None:
        """Validate policy ranges and identifiers."""
        cleaned_id = self.audience_id.strip()
        if not cleaned_id:
            raise AudiencePolicyError("Audience policy id is required.")
        if len(self.allowed_claim_confidences) != 2:
            raise AudiencePolicyError("allowed_claim_confidences must contain exactly two values.")
        min_conf, max_conf = self.allowed_claim_confidences
        if min_conf < 0.0 or max_conf > 1.0 or min_conf > max_conf:
            raise AudiencePolicyError("allowed_claim_confidences must be within 0.0-1.0 and ordered min <= max.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AudiencePolicy":
        policy = cls(
            audience_id=str(payload.get("audience_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            allowed_node_types=[str(item) for item in payload.get("allowed_node_types", [])],
            blocked_node_types=[str(item) for item in payload.get("blocked_node_types", [])],
            allowed_claim_confidences=tuple(payload.get("allowed_claim_confidences", (0.0, 1.0))),  # type: ignore[arg-type]
            redact_fields=[str(item) for item in payload.get("redact_fields", [])],
            output_format=str(payload.get("output_format") or "brief"),  # type: ignore[arg-type]
            delivery=str(payload.get("delivery") or "stdout"),  # type: ignore[arg-type]
            delivery_target=str(payload.get("delivery_target")) if payload.get("delivery_target") is not None else None,
            include_provenance=bool(payload.get("include_provenance", False)),
            include_contested=bool(payload.get("include_contested", False)),
        )
        policy.validate()
        return policy


class PolicyEngine:
    """Validate, preview, and compile audience-specific Mind outputs."""

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = Path(store_dir)

    def _load_policy_payload(self, mind_id: str) -> dict[str, Any]:
        path = audience_policy_path(self.store_dir, mind_id)
        if not path.exists():
            return {"mind": mind_id, "policies": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_policy_payload(self, mind_id: str, payload: dict[str, Any]) -> None:
        path = audience_policy_path(self.store_dir, mind_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked_path(path):
            atomic_write_json(path, payload)

    def add_policy(self, mind_id: str, policy: AudiencePolicy) -> dict[str, Any]:
        """Persist an audience policy on a Mind."""
        load_mind_manifest(self.store_dir, mind_id)
        policy.validate()
        payload = self._load_policy_payload(mind_id)
        policies = dict(payload.get("policies") or {})
        policies[policy.audience_id] = policy.to_dict()
        payload = {"mind": mind_id, "policies": policies}
        self._save_policy_payload(mind_id, payload)
        return {
            "status": "ok",
            "mind": mind_id,
            "audience_id": policy.audience_id,
            "policy_count": len(policies),
            "policy": policy.to_dict(),
        }

    def list_policies(self, mind_id: str) -> dict[str, Any]:
        """List audience policies configured on a Mind."""
        load_mind_manifest(self.store_dir, mind_id)
        payload = self._load_policy_payload(mind_id)
        policies = [
            AudiencePolicy.from_dict(policy).to_dict() for _, policy in sorted((payload.get("policies") or {}).items())
        ]
        return {"status": "ok", "mind": mind_id, "policy_count": len(policies), "policies": policies}

    def get_policy(self, mind_id: str, audience_id: str) -> AudiencePolicy:
        """Return a configured policy or raise a named error."""
        payload = self._load_policy_payload(mind_id)
        raw = dict(payload.get("policies") or {}).get(audience_id)
        if raw is None:
            raise UnknownAudiencePolicyError(f"Audience '{audience_id}' is not configured for Mind '{mind_id}'.")
        return AudiencePolicy.from_dict(raw)

    def _render_markdown(self, graph: CortexGraph, *, heading: str, include_provenance: bool) -> str:
        lines = [f"# {heading}", ""]
        ranked = sorted(graph.nodes.values(), key=lambda node: (-float(node.confidence or 0.0), node.label.lower()))
        if not ranked:
            lines.append("No facts matched this audience policy.")
            return "\n".join(lines) + "\n"
        for node in ranked:
            tags = ", ".join(node.tags) if node.tags else "untagged"
            lines.append(f"- {node.label} [{tags}]")
            if node.brief:
                lines.append(f"  {node.brief}")
            if include_provenance and node.provenance:
                sources = ", ".join(
                    sorted(
                        {
                            str(item.get("source_label") or item.get("source") or "")
                            for item in node.provenance
                            if str(item.get("source_label") or item.get("source") or "").strip()
                        }
                    )
                )
                if sources:
                    lines.append(f"  Sources: {sources}")
        lines.append("")
        return "\n".join(lines)

    def _redact_node(self, node_payload: dict[str, Any], *, redact_fields: list[str]) -> tuple[dict[str, Any], int]:
        redacted = dict(node_payload)
        count = 0
        for field_name in redact_fields:
            if field_name in redacted:
                redacted.pop(field_name, None)
                count += 1
            elif field_name in redacted.get("properties", {}):
                redacted["properties"] = dict(redacted["properties"])
                redacted["properties"].pop(field_name, None)
                count += 1
        return redacted, count

    def _strip_redacted_fields_from_serialized(
        self, payload: dict[str, Any], *, redact_fields: list[str]
    ) -> dict[str, Any]:
        if not redact_fields:
            return payload
        serialized = json.loads(json.dumps(payload))
        graph_nodes = ((serialized.get("graph") or {}).get("nodes")) or {}
        for node in graph_nodes.values():
            for field_name in redact_fields:
                node.pop(field_name, None)
                if isinstance(node.get("properties"), dict):
                    node["properties"].pop(field_name, None)
        return serialized

    def _filter_graph(self, graph: CortexGraph, policy: AudiencePolicy) -> tuple[CortexGraph, dict[str, Any]]:
        min_conf, max_conf = policy.allowed_claim_confidences
        filtered = CortexGraph(schema_version=graph.schema_version, meta=dict(graph.meta))
        included: list[dict[str, Any]] = []
        redacted: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        redaction_count = 0

        for node in graph.nodes.values():
            node_types = set(node.tags)
            blocked = bool(policy.blocked_node_types and node_types.intersection(policy.blocked_node_types))
            allowed = not policy.allowed_node_types or bool(node_types.intersection(policy.allowed_node_types))
            contested = bool(
                node.properties.get("contested")
                or node.properties.get("candidate")
                or node.properties.get("claim_contested")
            )
            in_confidence_range = min_conf <= float(node.confidence or 0.0) <= max_conf
            if blocked or not allowed or not in_confidence_range or (contested and not policy.include_contested):
                excluded.append(
                    {
                        "id": node.id,
                        "label": node.label,
                        "reason": "blocked"
                        if blocked
                        else "type_excluded"
                        if not allowed
                        else "confidence_excluded"
                        if not in_confidence_range
                        else "contested_excluded",
                    }
                )
                continue
            payload = node.to_dict()
            if not policy.include_provenance:
                for field_name in ("provenance", "source_quotes", "snapshots"):
                    if payload.get(field_name):
                        payload.pop(field_name, None)
                        redaction_count += 1
                payload.get("properties", {}).pop("claim_history", None)
            if not policy.include_contested:
                if payload.get("properties", {}).pop("contested", None) is not None:
                    redaction_count += 1
            payload, node_redactions = self._redact_node(payload, redact_fields=policy.redact_fields)
            redaction_count += node_redactions
            filtered.add_node(type(node).from_dict(payload))
            included.append({"id": node.id, "label": node.label})
            if node_redactions or (not policy.include_provenance and node.provenance):
                redacted.append({"id": node.id, "label": node.label})

        for edge in graph.edges.values():
            if edge.source_id in filtered.nodes and edge.target_id in filtered.nodes:
                filtered.add_edge(type(edge).from_dict(edge.to_dict()))

        preview = {
            "included": included,
            "redacted": redacted,
            "excluded": excluded,
            "redaction_count": redaction_count,
        }
        return filtered, preview

    def _render_output(self, graph: CortexGraph, policy: AudiencePolicy) -> Any:
        heading = policy.display_name or policy.audience_id.replace("-", " ").title()
        if policy.output_format == "raw":
            return self._strip_redacted_fields_from_serialized(
                graph.export_v5(),
                redact_fields=policy.redact_fields,
            )
        if policy.output_format == "pack":
            payload = {
                "graph": graph.export_v5(),
                "facts": [
                    {
                        "id": node.id,
                        "label": node.label,
                        "tags": list(node.tags),
                        "confidence": round(float(node.confidence or 0.0), 2),
                    }
                    for node in sorted(graph.nodes.values(), key=lambda item: item.label.lower())
                ],
            }
            payload["graph"] = self._strip_redacted_fields_from_serialized(
                payload["graph"],
                redact_fields=policy.redact_fields,
            )
            return payload
        return self._render_markdown(graph, heading=heading, include_provenance=policy.include_provenance)

    def preview(self, mind_id: str, audience_id: str) -> dict[str, Any]:
        """Preview audience policy filtering without writing output."""
        from cortex.minds import _resolve_core_graph

        load_mind_manifest(self.store_dir, mind_id)
        policy = self.get_policy(mind_id, audience_id)
        graph, graph_ref, graph_source = _resolve_core_graph(self.store_dir, mind_id)
        filtered, preview = self._filter_graph(graph, policy)
        return {
            "status": "ok",
            "mind": mind_id,
            "audience_id": audience_id,
            "graph_ref": graph_ref,
            "graph_source": graph_source,
            "node_count_in": len(graph.nodes),
            "node_count_out": len(filtered.nodes),
            "policy": policy.to_dict(),
            **preview,
            "output": self._render_output(filtered, policy),
        }

    def compile(self, mind_id: str, audience_id: str) -> dict[str, Any]:
        """Compile and log an audience-specific output."""
        payload = self.preview(mind_id, audience_id)
        policy = AudiencePolicy.from_dict(payload["policy"])
        compiled_at = _iso_now()
        log_entry = {
            "timestamp": compiled_at,
            "audience_id": audience_id,
            "mind_id": mind_id,
            "node_count_in": payload["node_count_in"],
            "node_count_out": payload["node_count_out"],
            "redaction_count": payload["redaction_count"],
        }
        log_path = audience_log_path(self.store_dir, mind_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with locked_path(log_path):
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        delivered_to = ""
        if policy.delivery == "file" and policy.delivery_target:
            target_path = Path(policy.delivery_target)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            output = payload["output"]
            if isinstance(output, str):
                target_path.write_text(output, encoding="utf-8")
            else:
                target_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
            delivered_to = str(target_path)

        return {
            **payload,
            "compiled_at": compiled_at,
            "delivered_to": delivered_to,
        }

    def read_log(self, mind_id: str, audience_id: str = "") -> dict[str, Any]:
        """Read audience compilation history."""
        log_path = audience_log_path(self.store_dir, mind_id)
        entries: list[dict[str, Any]] = []
        if log_path.exists():
            with log_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    entry = json.loads(raw)
                    if audience_id and str(entry.get("audience_id") or "") != audience_id:
                        continue
                    entries.append(entry)
        return {
            "status": "ok",
            "mind": mind_id,
            "audience_id": audience_id,
            "entry_count": len(entries),
            "entries": entries,
        }


__all__ = [
    "AudiencePolicy",
    "AudiencePolicyError",
    "PolicyEngine",
    "UnknownAudiencePolicyError",
    "audience_log_path",
    "audience_policy_path",
]
