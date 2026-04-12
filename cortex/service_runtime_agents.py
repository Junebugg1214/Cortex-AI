from __future__ import annotations

from pathlib import Path
from typing import Any

from cortex.agent.conflict_monitor import (
    DEFAULT_LOG_DIR,
    ConflictMonitor,
    ConflictMonitorConfig,
    conflict_status,
    load_pending_conflicts,
    review_pending_conflicts_with_decisions,
)
from cortex.agent.context_dispatcher import ContextDispatcher, dispatcher_status
from cortex.agent.events import AgentEvent, EventType, OutputFormat, normalize_delivery_target, normalize_output_format
from cortex.minds import list_minds, mind_status


def _resolved_log_dir(value: str = "") -> Path:
    return Path(value).expanduser().resolve() if value else DEFAULT_LOG_DIR


def _resolved_output_dir(value: str = "") -> Path | None:
    return Path(value).expanduser().resolve() if value else None


class MemoryRuntimeAgentMixin:
    def _accessible_agent_mind_ids(self, *, namespace: str | None = None) -> set[str] | None:
        if namespace is None:
            return None
        payload = list_minds(self.store_dir, namespace=namespace)
        return {
            str(item.get("mind", "")).strip()
            for item in payload.get("minds", [])
            if isinstance(item, dict) and str(item.get("mind", "")).strip()
        }

    def _require_agent_mind(self, mind_id: str, *, namespace: str | None = None) -> str:
        cleaned = str(mind_id or "").strip()
        if not cleaned:
            raise ValueError("mind_id is required.")
        mind_status(self.store_dir, cleaned, namespace=namespace)
        return cleaned

    def _filter_agent_records(
        self,
        records: list[dict[str, Any]],
        *,
        accessible_ids: set[str] | None,
    ) -> list[dict[str, Any]]:
        if accessible_ids is None:
            return [dict(item) for item in records if isinstance(item, dict)]
        return [
            dict(item)
            for item in records
            if isinstance(item, dict) and str(item.get("mind_id", "")).strip() in accessible_ids
        ]

    def _validate_agent_event(self, event: AgentEvent, *, namespace: str | None = None) -> None:
        if namespace is None:
            return
        if event.event_type is EventType.PROJECT_STAGE_CHANGED:
            candidate = str(event.payload.get("mind_id") or event.payload.get("project_id") or "").strip()
            if not candidate:
                raise ValueError("mind_id is required for namespace-scoped PROJECT_STAGE_CHANGED events.")
            self._require_agent_mind(candidate, namespace=namespace)
            return
        candidate = str(event.payload.get("mind_id", "")).strip()
        if not candidate:
            raise ValueError("mind_id is required for namespace-scoped agent events.")
        self._require_agent_mind(candidate, namespace=namespace)

    def agent_status(self, *, namespace: str | None = None) -> dict[str, Any]:
        accessible_ids = self._accessible_agent_mind_ids(namespace=namespace)
        conflict_payload = conflict_status(self.store_dir)
        runtime_payload = dispatcher_status(self.store_dir)
        pending_conflicts = self._filter_agent_records(
            conflict_payload.get("pending_conflicts", []),
            accessible_ids=accessible_ids,
        )
        active_monitors = self._filter_agent_records(
            conflict_payload.get("active_monitors", []),
            accessible_ids=accessible_ids,
        )
        scheduled_dispatches = self._filter_agent_records(
            runtime_payload.get("scheduled_dispatches", []),
            accessible_ids=accessible_ids,
        )
        return {
            "status": "ok",
            "active_monitors": active_monitors,
            "pending_conflicts": pending_conflicts,
            "pending_count": len(pending_conflicts),
            "scheduled_dispatches": scheduled_dispatches,
            "scheduled_count": len(scheduled_dispatches),
            "release": self.release(),
        }

    def agent_monitor_run(
        self,
        *,
        mind_id: str = "",
        auto_resolve_threshold: float = 0.85,
        log_dir: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        resolved_mind = str(mind_id or "").strip() or None
        if namespace is not None and resolved_mind is None:
            raise ValueError("mind_id is required for namespace-scoped agent monitoring.")
        if resolved_mind is not None:
            resolved_mind = self._require_agent_mind(resolved_mind, namespace=namespace)
        payload = ConflictMonitor(
            ConflictMonitorConfig(
                store_dir=self.store_dir,
                mind_id=resolved_mind,
                auto_resolve_threshold=float(auto_resolve_threshold),
                interactive=False,
                log_dir=_resolved_log_dir(log_dir),
            )
        ).run_cycle()
        payload["release"] = self.release()
        return payload

    def agent_compile(
        self,
        *,
        mind_id: str,
        audience_id: str = "",
        output_format: str = "brief",
        delivery: str = "local_file",
        webhook_url: str = "",
        output_dir: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        resolved_mind = self._require_agent_mind(mind_id, namespace=namespace)
        normalized_output = normalize_output_format(output_format)
        normalized_delivery = normalize_delivery_target(delivery)
        audience = audience_id or ("recruiter" if normalized_output is OutputFormat.CV else "general")
        dispatcher = ContextDispatcher(store_dir=self.store_dir, output_root=_resolved_output_dir(output_dir))
        payload = dispatcher.dispatch(
            AgentEvent.create(
                EventType.MANUAL_TRIGGER,
                {
                    "mind_id": resolved_mind,
                    "audience_id": audience,
                    "output_format": normalized_output.value,
                    "delivery": normalized_delivery.value,
                    "webhook_url": webhook_url,
                },
            )
        )
        payload["release"] = self.release()
        return payload

    def agent_dispatch(
        self,
        *,
        event: str,
        payload: dict[str, Any],
        output_dir: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        dispatcher = ContextDispatcher(store_dir=self.store_dir, output_root=_resolved_output_dir(output_dir))
        normalized_event = AgentEvent.create(event, payload)
        self._validate_agent_event(normalized_event, namespace=namespace)
        result = dispatcher.dispatch(normalized_event)
        result["release"] = self.release()
        return result

    def agent_schedule(
        self,
        *,
        mind_id: str,
        audience_id: str,
        cron_expression: str,
        output_format: str,
        delivery: str = "local_file",
        webhook_url: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        resolved_mind = self._require_agent_mind(mind_id, namespace=namespace)
        dispatcher = ContextDispatcher(store_dir=self.store_dir)
        payload = dispatcher.register_schedule(
            mind_id=resolved_mind,
            audience_id=audience_id,
            cron_expression=cron_expression,
            output_format=normalize_output_format(output_format),
            delivery=normalize_delivery_target(delivery),
            webhook_url=webhook_url,
        )
        payload["release"] = self.release()
        return payload

    def agent_review_conflicts(
        self,
        *,
        decisions: list[dict[str, Any]] | None = None,
        log_dir: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        accessible_ids = self._accessible_agent_mind_ids(namespace=namespace)
        allowed_conflict_ids = None
        if accessible_ids is not None:
            allowed_conflict_ids = {
                proposal.conflict_id
                for proposal in load_pending_conflicts(self.store_dir)
                if proposal.mind_id in accessible_ids
            }
        payload = review_pending_conflicts_with_decisions(
            self.store_dir,
            decisions or [],
            log_dir=_resolved_log_dir(log_dir),
            allowed_conflict_ids=allowed_conflict_ids,
        )
        payload["release"] = self.release()
        return payload


__all__ = ["MemoryRuntimeAgentMixin"]
