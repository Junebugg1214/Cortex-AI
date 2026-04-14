"""Event-driven context compilation and delivery for Cortex."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from cortex.agent.conflict_monitor import professional_history_flags
from cortex.agent.events import (
    AgentEvent,
    DeliveryTarget,
    EventType,
    OutputFormat,
    normalize_delivery_target,
    normalize_output_format,
)
from cortex.atomic_io import atomic_write_json, atomic_write_text, locked_path
from cortex.graph import CortexGraph, Node
from cortex.mind_runtime import _compose_graph_for_target
from cortex.minds import resolve_default_mind
from cortex.runtime_control import ShutdownController
from cortex.runtime_logging import get_logger, log_operation
from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy, apply_disclosure

DEFAULT_OUTPUT_DIRNAME = "output"
LOGGER = get_logger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _agent_state_dir(store_dir: Path) -> Path:
    return Path(store_dir) / "agent"


def _schedule_registry_path(store_dir: Path) -> Path:
    return _agent_state_dir(store_dir) / "dispatch_schedules.json"


def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    if not isinstance(payload, dict):
        return dict(default)
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_path(path):
        atomic_write_json(path, payload)


def _normalized_timestamp(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return cleaned
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _lineage_for_node(node: Node) -> list[dict[str, Any]]:
    lineage: list[dict[str, Any]] = []
    for item in list(node.provenance) + list(node.snapshots):
        if not isinstance(item, dict):
            continue
        lineage.append(
            {
                "source": str(item.get("source", "")).strip(),
                "method": str(item.get("method", "")).strip(),
                "timestamp": _normalized_timestamp(str(item.get("timestamp", ""))),
                "quote": str(item.get("quote", "") or item.get("source_quote", "")).strip(),
            }
        )
    if not lineage:
        lineage.append(
            {
                "source": "graph_state",
                "method": "graph_state",
                "timestamp": _normalized_timestamp(node.last_seen or node.first_seen),
                "quote": "",
            }
        )
    lineage.sort(key=lambda item: item.get("timestamp", ""))
    return lineage


@dataclass(frozen=True, slots=True)
class AudienceProfile:
    """Audience-specific routing preferences."""

    audience_id: str
    portable_target: str
    policy_name: str
    route_tags: tuple[str, ...]
    default_delivery: DeliveryTarget = DeliveryTarget.LOCAL_FILE


AUDIENCE_PROFILES: dict[str, AudienceProfile] = {
    "general": AudienceProfile(
        audience_id="general",
        portable_target="chatgpt",
        policy_name="full",
        route_tags=(
            "identity",
            "professional_context",
            "business_context",
            "active_priorities",
            "technical_expertise",
            "domain_knowledge",
            "constraints",
            "communication_preferences",
        ),
    ),
    "team": AudienceProfile(
        audience_id="team",
        portable_target="chatgpt",
        policy_name="full",
        route_tags=(
            "professional_context",
            "business_context",
            "active_priorities",
            "technical_expertise",
            "domain_knowledge",
            "constraints",
        ),
    ),
    "attorney": AudienceProfile(
        audience_id="attorney",
        portable_target="grok",
        policy_name="full",
        route_tags=(
            "identity",
            "professional_context",
            "business_context",
            "work_history",
            "education_history",
            "relationships",
            "constraints",
            "values",
        ),
    ),
    "recruiter": AudienceProfile(
        audience_id="recruiter",
        portable_target="chatgpt",
        policy_name="professional",
        route_tags=(
            "identity",
            "professional_context",
            "work_history",
            "education_history",
            "technical_expertise",
            "business_context",
        ),
    ),
    "onboarding": AudienceProfile(
        audience_id="onboarding",
        portable_target="codex",
        policy_name="full",
        route_tags=(
            "identity",
            "professional_context",
            "business_context",
            "active_priorities",
            "technical_expertise",
            "domain_knowledge",
            "constraints",
            "relationships",
        ),
    ),
}


@dataclass(slots=True)
class CompilationRule:
    """Resolved compilation rule for one event."""

    event_type: EventType
    mind_id: str
    audience_id: str
    output_format: OutputFormat
    delivery: DeliveryTarget
    webhook_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "mind_id": self.mind_id,
            "audience_id": self.audience_id,
            "output_format": self.output_format.value,
            "delivery": self.delivery.value,
            "webhook_url": self.webhook_url,
        }


@dataclass(slots=True)
class ScheduledDispatch:
    """Persisted recurring dispatch registration."""

    schedule_id: str
    mind_id: str
    audience_id: str
    cron_expression: str
    output_format: OutputFormat
    delivery: DeliveryTarget
    webhook_url: str
    created_at: str
    last_run_at: str
    next_run_at: str
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "mind_id": self.mind_id,
            "audience_id": self.audience_id,
            "cron_expression": self.cron_expression,
            "output_format": self.output_format.value,
            "delivery": self.delivery.value,
            "webhook_url": self.webhook_url,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScheduledDispatch":
        return cls(
            schedule_id=str(payload.get("schedule_id", "")),
            mind_id=str(payload.get("mind_id", "")),
            audience_id=str(payload.get("audience_id", "")),
            cron_expression=str(payload.get("cron_expression", "")),
            output_format=normalize_output_format(str(payload.get("output_format", "brief"))),
            delivery=normalize_delivery_target(str(payload.get("delivery", DeliveryTarget.LOCAL_FILE.value))),
            webhook_url=str(payload.get("webhook_url", "")),
            created_at=str(payload.get("created_at", "")),
            last_run_at=str(payload.get("last_run_at", "")),
            next_run_at=str(payload.get("next_run_at", "")),
            active=bool(payload.get("active", True)),
        )


def _audience_profile(audience_id: str) -> AudienceProfile:
    normalized = str(audience_id or "").strip().lower() or "general"
    return AUDIENCE_PROFILES.get(normalized, AUDIENCE_PROFILES["general"])


def _audience_policy(profile: AudienceProfile) -> DisclosurePolicy:
    base = BUILTIN_POLICIES.get(profile.policy_name, BUILTIN_POLICIES["full"])
    return DisclosurePolicy(
        name=f"audience-{profile.audience_id}",
        include_tags=list(profile.route_tags),
        exclude_tags=list(base.exclude_tags),
        min_confidence=base.min_confidence,
        redact_properties=list(base.redact_properties),
        max_nodes=base.max_nodes,
    )


def _parse_field(field: str, minimum: int, maximum: int, *, allow_seven: bool = False) -> set[int]:
    cleaned = field.strip()
    allowed: set[int] = set()
    if cleaned == "*":
        return set(range(minimum, maximum + 1))
    for part in cleaned.split(","):
        token = part.strip()
        if not token:
            continue
        step = 1
        if "/" in token:
            token, step_text = token.split("/", 1)
            step = int(step_text)
        if token == "*":
            start, end = minimum, maximum
        elif "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(token)
        if allow_seven and start == 7:
            start = 0
        if allow_seven and end == 7:
            end = 0
        if start < minimum or end > maximum or step <= 0:
            raise ValueError("Unsupported cron field range.")
        if start <= end:
            allowed.update(range(start, end + 1, step))
        else:
            allowed.update(range(start, maximum + 1, step))
            allowed.update(range(minimum, end + 1, step))
    return allowed


def _cron_matches(expression: str, when: datetime) -> bool:
    minute, hour, day, month, weekday = expression.split()
    allowed_minutes = _parse_field(minute, 0, 59)
    allowed_hours = _parse_field(hour, 0, 23)
    allowed_days = _parse_field(day, 1, 31)
    allowed_months = _parse_field(month, 1, 12)
    allowed_weekdays = _parse_field(weekday, 0, 6, allow_seven=True)
    weekday_value = (when.weekday() + 1) % 7
    return (
        when.minute in allowed_minutes
        and when.hour in allowed_hours
        and when.day in allowed_days
        and when.month in allowed_months
        and weekday_value in allowed_weekdays
    )


def next_cron_run(expression: str, *, after: datetime | None = None) -> datetime:
    """Return the next datetime that satisfies the cron expression."""
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("cron_expression must use standard 5-field cron syntax.")
    current = (after or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    candidate = current + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if _cron_matches(expression, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(f"Unable to find next run for cron_expression: {expression}")


def load_schedules(store_dir: Path) -> list[ScheduledDispatch]:
    payload = _read_json(_schedule_registry_path(store_dir), default={"schedules": []})
    return [ScheduledDispatch.from_dict(item) for item in payload.get("schedules", []) if isinstance(item, dict)]


def _save_schedules(store_dir: Path, schedules: list[ScheduledDispatch]) -> None:
    _write_json(_schedule_registry_path(store_dir), {"schedules": [item.to_dict() for item in schedules]})


def _render_with_attribution(node: Node) -> str:
    parts = [node.label]
    if node.brief and node.brief != node.label:
        parts.append(node.brief)
    attribution = "; ".join(
        filter(
            None,
            (
                f"{item.get('source', 'unknown')} {item.get('timestamp', '')}".strip()
                for item in _lineage_for_node(node)
            ),
        )
    )
    if attribution:
        parts.append(f"Sources: {attribution}")
    return " — ".join(parts)


def _node_payload(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "label": node.label,
        "brief": node.brief,
        "full_description": node.full_description,
        "tags": list(node.tags),
        "confidence": round(node.confidence, 4),
        "status": node.status,
        "valid_from": node.valid_from,
        "valid_to": node.valid_to,
        "properties": dict(node.properties),
        "attribution": _lineage_for_node(node),
    }


def _sorted_nodes(graph: CortexGraph) -> list[Node]:
    return sorted(graph.nodes.values(), key=lambda item: (-item.confidence, item.label.lower()))


def _professional_sections(graph: CortexGraph) -> dict[str, list[dict[str, Any]]]:
    experience: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = []
    publications: list[dict[str, Any]] = []
    certifications: list[dict[str, Any]] = []
    achievements: list[dict[str, Any]] = []
    for node in _sorted_nodes(graph):
        lowered = " ".join([node.label, node.brief, node.full_description, json.dumps(node.properties)]).lower()
        payload = _node_payload(node)
        if "work_history" in node.tags or "professional_context" in node.tags:
            experience.append(payload)
            continue
        if "technical_expertise" in node.tags:
            skills.append(payload)
            continue
        if "publication" in lowered or "paper" in lowered or "article" in lowered or "book" in lowered:
            publications.append(payload)
            continue
        if "certification" in lowered or "certified" in lowered or "license" in lowered:
            certifications.append(payload)
            continue
        if "achievement" in lowered or "award" in lowered or "shipped" in lowered or "launched" in lowered:
            achievements.append(payload)
            continue
        if "active_priorities" in node.tags or "business_context" in node.tags:
            achievements.append(payload)
    return {
        "employment_history": experience,
        "skills": skills,
        "publications": publications,
        "certifications": certifications,
        "achievements": achievements,
    }


def _markdown_list(title: str, items: list[dict[str, Any]]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        lines.append("- None yet.")
        lines.append("")
        return lines
    for item in items:
        entry = item["label"]
        if item.get("brief"):
            entry = f"{entry} — {item['brief']}"
        lines.append(f"- {entry}")
        attribution = "; ".join(
            f"{lineage.get('source', 'unknown')} {lineage.get('timestamp', '')}".strip()
            for lineage in item.get("attribution", [])
            if lineage.get("source") or lineage.get("timestamp")
        )
        if attribution:
            lines.append(f"  Source: {attribution}")
    lines.append("")
    return lines


def _build_cv_payload(mind_id: str, graph: CortexGraph) -> tuple[str, dict[str, Any]]:
    professional_graph = apply_disclosure(graph, BUILTIN_POLICIES["professional"])
    sections = _professional_sections(professional_graph)
    flags = professional_history_flags(professional_graph)
    markdown: list[str] = [
        f"# CV — {mind_id}",
        "",
        "## Summary",
        "",
        f"- Professional facts: {len(professional_graph.nodes)}",
        f"- Flags: {len(flags)}",
        "",
    ]
    markdown.extend(_markdown_list("Employment History", sections["employment_history"]))
    markdown.extend(_markdown_list("Skills", sections["skills"]))
    markdown.extend(_markdown_list("Publications", sections["publications"]))
    markdown.extend(_markdown_list("Certifications", sections["certifications"]))
    markdown.extend(_markdown_list("Achievements", sections["achievements"]))
    markdown.extend(["## Flags", ""])
    if not flags:
        markdown.append("- No professional-history gaps or conflicts detected.")
    else:
        for flag in flags:
            markdown.append(
                f"- [{flag.get('type', 'flag')}] {flag.get('summary', flag.get('label', flag.get('kind', '')))}"
            )
    markdown.append("")
    payload = {
        "mind": mind_id,
        "generated_at": _utc_now(),
        "output_format": OutputFormat.CV.value,
        "employment_history": sections["employment_history"],
        "skills": sections["skills"],
        "publications": sections["publications"],
        "certifications": sections["certifications"],
        "achievements": sections["achievements"],
        "flags": flags,
        "professional_graph": professional_graph.export_v5(),
    }
    return "\n".join(markdown).rstrip() + "\n", payload


def _build_generic_payload(
    *,
    mind_id: str,
    audience_id: str,
    output_format: OutputFormat,
    graph: CortexGraph,
) -> tuple[str, dict[str, Any]]:
    nodes = _sorted_nodes(graph)
    facts = [_node_payload(node) for node in nodes]
    title_map = {
        OutputFormat.PACK: "Context Pack",
        OutputFormat.BRIEF: "Brief",
        OutputFormat.ONBOARDING_DOC: "Onboarding Doc",
        OutputFormat.SUMMARY: "Summary",
    }
    markdown: list[str] = [
        f"# {title_map.get(output_format, 'Context')} — {mind_id}",
        "",
        f"- Audience: {audience_id}",
        f"- Facts: {len(facts)}",
        "",
    ]
    limit = {
        OutputFormat.PACK: 20,
        OutputFormat.BRIEF: 8,
        OutputFormat.ONBOARDING_DOC: 16,
        OutputFormat.SUMMARY: 6,
    }.get(output_format, 8)
    for node in nodes[:limit]:
        markdown.append(f"- {_render_with_attribution(node)}")
    markdown.append("")
    payload = {
        "mind": mind_id,
        "generated_at": _utc_now(),
        "audience": audience_id,
        "output_format": output_format.value,
        "fact_count": len(facts),
        "facts": facts,
        "graph": graph.export_v5(),
    }
    return "\n".join(markdown), payload


def _output_root(output_root: Path | None) -> Path:
    return (output_root or (Path.cwd() / DEFAULT_OUTPUT_DIRNAME)).resolve()


def _write_output_files(
    *,
    output_root: Path | None,
    output_format: OutputFormat,
    markdown: str,
    payload: dict[str, Any],
) -> list[str]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    stem = f"{output_format.value}_{timestamp}"
    base = _output_root(output_root)
    base.mkdir(parents=True, exist_ok=True)
    markdown_path = base / f"{stem}.md"
    json_path = base / f"{stem}.json"
    atomic_write_text(markdown_path, markdown, encoding="utf-8")
    atomic_write_json(json_path, payload)
    return [str(markdown_path), str(json_path)]


def _deliver_webhook(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            body = response.read().decode("utf-8", errors="replace")
        return {"status": "ok", "code": 200, "response": body}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "error", "code": exc.code, "error": body or str(exc)}
    except urllib.error.URLError as exc:
        return {"status": "error", "code": 0, "error": str(exc.reason)}


class ContextDispatcher:
    """Resolve events into audience-specific context compilations."""

    def __init__(self, *, store_dir: Path, output_root: Path | None = None) -> None:
        self.store_dir = Path(store_dir)
        self.output_root = output_root

    def resolve_rule(self, event: AgentEvent) -> CompilationRule:
        """Resolve a built-in event into a concrete compilation rule."""
        payload = dict(event.payload)
        delivery = normalize_delivery_target(str(payload.get("delivery", DeliveryTarget.LOCAL_FILE.value)))
        webhook_url = str(payload.get("webhook_url", "")).strip()
        if event.event_type is EventType.PROJECT_STAGE_CHANGED:
            new_stage = str(payload.get("new_stage", "")).strip().lower()
            output_format = normalize_output_format(
                str(payload.get("output_format", "onboarding_doc" if new_stage in {"launch", "release"} else "pack"))
            )
            audience_id = str(
                payload.get("audience_id", "onboarding" if output_format is OutputFormat.ONBOARDING_DOC else "team")
            ).strip()
            mind_id = str(payload.get("mind_id") or payload.get("project_id") or "").strip()
        elif event.event_type is EventType.SCHEDULED_REVIEW:
            output_format = normalize_output_format(str(payload.get("output_format", "brief")))
            audience_id = str(payload["audience_id"]).strip()
            mind_id = str(payload["mind_id"]).strip()
        elif event.event_type is EventType.FACT_THRESHOLD_REACHED:
            output_format = normalize_output_format(str(payload.get("output_format", "summary")))
            audience_id = str(payload.get("audience_id", "team")).strip()
            mind_id = str(payload["mind_id"]).strip()
        else:
            output_format = normalize_output_format(str(payload["output_format"]))
            audience_id = str(payload["audience_id"]).strip()
            mind_id = str(payload["mind_id"]).strip()

        if not mind_id:
            resolved_default = resolve_default_mind(self.store_dir)
            if resolved_default is None:
                raise ValueError("No Mind was supplied and no default Mind is configured.")
            mind_id = resolved_default

        return CompilationRule(
            event_type=event.event_type,
            mind_id=mind_id,
            audience_id=audience_id or "general",
            output_format=output_format,
            delivery=delivery,
            webhook_url=webhook_url,
        )

    def _load_graph(self, *, mind_id: str, audience_id: str) -> tuple[CortexGraph, dict[str, Any]]:
        profile = _audience_profile(audience_id)
        composed = _compose_graph_for_target(
            self.store_dir,
            mind_id,
            target=profile.portable_target,
            task="",
            policy_name=profile.policy_name,
        )
        filtered = apply_disclosure(composed["composed_graph"], _audience_policy(profile))
        return filtered, composed

    def compile_context(
        self,
        *,
        mind_id: str,
        audience_id: str,
        output_format: OutputFormat,
    ) -> tuple[str, dict[str, Any]]:
        """Compile one audience-specific artifact for a Mind."""
        graph, composed = self._load_graph(mind_id=mind_id, audience_id=audience_id)
        if output_format is OutputFormat.CV:
            markdown, payload = _build_cv_payload(mind_id, composed["composed_graph"])
        else:
            markdown, payload = _build_generic_payload(
                mind_id=mind_id,
                audience_id=audience_id,
                output_format=output_format,
                graph=graph,
            )
        payload["base_graph_ref"] = composed["base_graph_ref"]
        payload["base_graph_source"] = composed["base_graph_source"]
        payload["included_brainpacks"] = [
            {"pack": item["pack"], "priority": item["priority"], "selection_reason": item["selection_reason"]}
            for item in composed["included_brainpacks"]
        ]
        return markdown, payload

    def dispatch(self, event: AgentEvent) -> dict[str, Any]:
        """Dispatch one event and deliver the compiled artifact."""
        rule = self.resolve_rule(event)
        markdown, payload = self.compile_context(
            mind_id=rule.mind_id,
            audience_id=rule.audience_id,
            output_format=rule.output_format,
        )
        result = {
            "status": "ok",
            "event": event.to_dict(),
            "rule": rule.to_dict(),
            "markdown": markdown,
            "payload": payload,
            "artifacts": [],
            "delivery_result": {},
        }

        if rule.delivery is DeliveryTarget.LOCAL_FILE:
            result["artifacts"] = _write_output_files(
                output_root=self.output_root,
                output_format=rule.output_format,
                markdown=markdown,
                payload=payload,
            )
            result["delivery_result"] = {"status": "ok", "target": rule.delivery.value}
            return result

        if rule.delivery is DeliveryTarget.STDOUT:
            result["delivery_result"] = {"status": "ok", "target": rule.delivery.value}
            return result

        if not rule.webhook_url:
            result["status"] = "delivery_failed"
            result["delivery_result"] = {"status": "error", "error": "webhook_url is required for webhook delivery"}
            return result

        delivery_payload = {
            "event": event.to_dict(),
            "rule": rule.to_dict(),
            "markdown": markdown,
            "payload": payload,
        }
        delivery_result = _deliver_webhook(rule.webhook_url, delivery_payload)
        result["delivery_result"] = delivery_result
        if delivery_result.get("status") != "ok":
            result["status"] = "delivery_failed"
        return result

    def register_schedule(
        self,
        *,
        mind_id: str,
        audience_id: str,
        cron_expression: str,
        output_format: OutputFormat,
        delivery: DeliveryTarget = DeliveryTarget.LOCAL_FILE,
        webhook_url: str = "",
    ) -> dict[str, Any]:
        """Persist a recurring trigger schedule."""
        if delivery is DeliveryTarget.REST_WEBHOOK and not webhook_url.strip():
            raise ValueError("webhook_url is required when delivery is webhook.")
        next_run = next_cron_run(cron_expression)
        schedules = load_schedules(self.store_dir)
        record = ScheduledDispatch(
            schedule_id=uuid4().hex[:16],
            mind_id=mind_id,
            audience_id=audience_id,
            cron_expression=cron_expression,
            output_format=output_format,
            delivery=delivery,
            webhook_url=webhook_url,
            created_at=_utc_now(),
            last_run_at="",
            next_run_at=next_run.isoformat().replace("+00:00", "Z"),
        )
        schedules.append(record)
        _save_schedules(self.store_dir, schedules)
        log_operation(
            LOGGER,
            logging.INFO,
            "dispatcher_schedule_register",
            "Registered recurring audience compilation.",
            schedule_id=record.schedule_id,
            mind_id=mind_id,
            audience_id=audience_id,
            delivery=delivery.value,
        )
        return {"status": "ok", "schedule": record.to_dict()}

    def run_due_schedules(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Execute any schedule whose next_run_at is due."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        schedules = load_schedules(self.store_dir)
        results: list[dict[str, Any]] = []
        changed = False
        for record in schedules:
            if not record.active:
                continue
            due_at = datetime.fromisoformat(record.next_run_at.replace("Z", "+00:00"))
            if due_at > current:
                continue
            event = AgentEvent.create(
                EventType.SCHEDULED_REVIEW,
                {
                    "mind_id": record.mind_id,
                    "audience_id": record.audience_id,
                    "cron_expression": record.cron_expression,
                    "output_format": record.output_format.value,
                    "delivery": record.delivery.value,
                    "webhook_url": record.webhook_url,
                },
            )
            try:
                dispatch_result = self.dispatch(event)
            except Exception as exc:
                dispatch_result = {
                    "status": "error",
                    "event": event.to_dict(),
                    "rule": {
                        "mind_id": record.mind_id,
                        "audience_id": record.audience_id,
                        "output_format": record.output_format.value,
                        "delivery": record.delivery.value,
                    },
                    "error": str(exc),
                }
                log_operation(
                    LOGGER,
                    logging.ERROR,
                    "dispatcher_schedule_run",
                    "Scheduled dispatch failed.",
                    exc_info=True,
                    schedule_id=record.schedule_id,
                    mind_id=record.mind_id,
                    audience_id=record.audience_id,
                    error=str(exc),
                )
            else:
                log_operation(
                    LOGGER,
                    logging.INFO,
                    "dispatcher_schedule_run",
                    "Scheduled dispatch completed.",
                    schedule_id=record.schedule_id,
                    mind_id=record.mind_id,
                    audience_id=record.audience_id,
                    status=dispatch_result.get("status", "ok"),
                )
            results.append(dispatch_result)
            record.last_run_at = current.isoformat().replace("+00:00", "Z")
            record.next_run_at = next_cron_run(record.cron_expression, after=current).isoformat().replace("+00:00", "Z")
            changed = True
        if changed:
            _save_schedules(self.store_dir, schedules)
        return {"status": "ok", "dispatched": len(results), "results": results}

    def watch(
        self,
        *,
        interval_seconds: int = 60,
        stop_check: Callable[[], bool] | None = None,
        shutdown_controller: ShutdownController | None = None,
    ) -> None:
        """Continuously poll recurring schedules and dispatch when due."""
        log_operation(
            LOGGER,
            logging.INFO,
            "dispatcher_watch_start",
            "Started dispatcher watch loop.",
            interval_seconds=interval_seconds,
        )
        while True:
            if stop_check is not None and stop_check():
                break
            if shutdown_controller is not None and shutdown_controller.stop_requested:
                break
            try:
                self.run_due_schedules()
            except Exception as exc:
                log_operation(
                    LOGGER,
                    logging.ERROR,
                    "dispatcher_watch_cycle",
                    "Dispatcher watch cycle failed.",
                    exc_info=True,
                    error=str(exc),
                )
            if shutdown_controller is not None:
                if shutdown_controller.wait(interval_seconds):
                    break
            else:
                time.sleep(interval_seconds)
        log_operation(
            LOGGER,
            logging.INFO,
            "dispatcher_watch_stop",
            "Stopped dispatcher watch loop.",
            reason=shutdown_controller.reason if shutdown_controller is not None else "",
        )


def dispatcher_status(store_dir: Path) -> dict[str, Any]:
    """Return scheduled-dispatch state for the shared agent status view."""
    schedules = load_schedules(store_dir)
    return {
        "scheduled_dispatches": [item.to_dict() for item in schedules],
        "scheduled_count": len(schedules),
    }


__all__ = [
    "ContextDispatcher",
    "ScheduledDispatch",
    "dispatcher_status",
    "load_schedules",
    "next_cron_run",
]
