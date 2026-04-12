"""Typed event schema for Cortex agent workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


def _utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class EventType(str, Enum):
    """Built-in agent trigger event types."""

    PROJECT_STAGE_CHANGED = "PROJECT_STAGE_CHANGED"
    SCHEDULED_REVIEW = "SCHEDULED_REVIEW"
    FACT_THRESHOLD_REACHED = "FACT_THRESHOLD_REACHED"
    MANUAL_TRIGGER = "MANUAL_TRIGGER"


class DeliveryTarget(str, Enum):
    """Supported output delivery targets."""

    LOCAL_FILE = "local_file"
    REST_WEBHOOK = "rest_webhook"
    STDOUT = "stdout"


class OutputFormat(str, Enum):
    """Supported compilation output formats."""

    PACK = "pack"
    BRIEF = "brief"
    CV = "cv"
    ONBOARDING_DOC = "onboarding_doc"
    SUMMARY = "summary"


def normalize_output_format(value: str) -> OutputFormat:
    """Normalize CLI and payload aliases into a supported output format."""
    cleaned = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias_map = {
        "pack": OutputFormat.PACK,
        "brief": OutputFormat.BRIEF,
        "cv": OutputFormat.CV,
        "resume": OutputFormat.CV,
        "onboarding": OutputFormat.ONBOARDING_DOC,
        "onboarding_doc": OutputFormat.ONBOARDING_DOC,
        "summary": OutputFormat.SUMMARY,
    }
    if cleaned not in alias_map:
        raise ValueError(
            "output_format must be one of: pack, brief, cv, onboarding-doc, or summary."
        )
    return alias_map[cleaned]


def normalize_delivery_target(value: str | None) -> DeliveryTarget:
    """Normalize delivery target aliases."""
    cleaned = str(value or DeliveryTarget.LOCAL_FILE.value).strip().lower().replace("-", "_")
    alias_map = {
        "local": DeliveryTarget.LOCAL_FILE,
        "local_file": DeliveryTarget.LOCAL_FILE,
        "file": DeliveryTarget.LOCAL_FILE,
        "webhook": DeliveryTarget.REST_WEBHOOK,
        "rest_webhook": DeliveryTarget.REST_WEBHOOK,
        "stdout": DeliveryTarget.STDOUT,
    }
    if cleaned not in alias_map:
        raise ValueError("delivery must be one of: local-file, webhook, or stdout.")
    return alias_map[cleaned]


def parse_event_type(value: str | EventType) -> EventType:
    """Normalize an event type string into the enum."""
    if isinstance(value, EventType):
        return value
    cleaned = str(value or "").strip().upper()
    try:
        return EventType(cleaned)
    except ValueError as exc:
        choices = ", ".join(item.value for item in EventType)
        raise ValueError(f"event must be one of: {choices}.") from exc


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


def _validate_payload(event_type: EventType, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate built-in event payload requirements while preserving extras."""
    normalized = {str(key): value for key, value in payload.items()}
    if event_type is EventType.PROJECT_STAGE_CHANGED:
        normalized["project_id"] = _require_string(normalized, "project_id")
        normalized["old_stage"] = _require_string(normalized, "old_stage")
        normalized["new_stage"] = _require_string(normalized, "new_stage")
        if "mind_id" in normalized:
            normalized["mind_id"] = str(normalized["mind_id"]).strip()
    elif event_type is EventType.SCHEDULED_REVIEW:
        normalized["mind_id"] = _require_string(normalized, "mind_id")
        normalized["audience_id"] = _require_string(normalized, "audience_id")
        normalized["cron_expression"] = _require_string(normalized, "cron_expression")
    elif event_type is EventType.FACT_THRESHOLD_REACHED:
        normalized["mind_id"] = _require_string(normalized, "mind_id")
        try:
            normalized["fact_count_delta"] = int(normalized.get("fact_count_delta", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("fact_count_delta must be an integer.") from exc
    elif event_type is EventType.MANUAL_TRIGGER:
        normalized["mind_id"] = _require_string(normalized, "mind_id")
        normalized["audience_id"] = _require_string(normalized, "audience_id")
        normalized["output_format"] = normalize_output_format(_require_string(normalized, "output_format")).value

    if "output_format" in normalized and str(normalized["output_format"]).strip():
        normalized["output_format"] = normalize_output_format(str(normalized["output_format"])).value
    if "delivery" in normalized and str(normalized["delivery"]).strip():
        normalized["delivery"] = normalize_delivery_target(str(normalized["delivery"])).value
    if "webhook_url" in normalized and normalized["webhook_url"] is not None:
        normalized["webhook_url"] = str(normalized["webhook_url"]).strip()
    if "audience_id" in normalized and normalized["audience_id"] is not None:
        normalized["audience_id"] = str(normalized["audience_id"]).strip()
    if "mind_id" in normalized and normalized["mind_id"] is not None:
        normalized["mind_id"] = str(normalized["mind_id"]).strip()
    return normalized


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """Normalized agent event payload."""

    event_type: EventType
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: uuid4().hex[:16])
    created_at: str = field(default_factory=_utc_now)

    @classmethod
    def create(cls, event_type: str | EventType, payload: Mapping[str, Any]) -> "AgentEvent":
        """Construct a validated event from a raw payload."""
        normalized_type = parse_event_type(event_type)
        normalized_payload = _validate_payload(normalized_type, payload)
        return cls(event_type=normalized_type, payload=normalized_payload)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event for storage or transport."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "created_at": self.created_at,
            "payload": dict(self.payload),
        }


__all__ = [
    "AgentEvent",
    "DeliveryTarget",
    "EventType",
    "OutputFormat",
    "normalize_delivery_target",
    "normalize_output_format",
    "parse_event_type",
]
