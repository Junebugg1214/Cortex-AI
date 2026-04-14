"""Shared agent entry points for Cortex autonomous workflows."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cortex.agent.conflict_monitor import (
    ConflictMonitor,
    ConflictMonitorConfig,
    conflict_status,
    review_pending_conflicts,
)
from cortex.agent.context_dispatcher import ContextDispatcher, dispatcher_status
from cortex.agent.events import (
    AgentEvent,
    DeliveryTarget,
    EventType,
    normalize_delivery_target,
    normalize_output_format,
)
from cortex.runtime_control import ShutdownController, install_shutdown_handlers


@dataclass(frozen=True)
class AgentCliContext:
    """Callbacks supplied by the shared CLI facade."""

    emit_result: Callable[[Any, str], int]
    echo: Callable[..., None]
    error: Callable[..., int]
    resolved_store_dir: Callable[[str | Path | None], Path]


def _output_root(path: str | None) -> Path | None:
    return Path(path).expanduser().resolve() if path else None


def _dispatch_text(ctx: AgentCliContext, result: dict[str, Any]) -> int:
    ctx.echo(f"Event: {result['event']['event_type']}")
    ctx.echo(f"Mind: {result['rule']['mind_id']}")
    ctx.echo(f"Audience: {result['rule']['audience_id']}")
    ctx.echo(f"Output: {result['rule']['output_format']}")
    ctx.echo(f"Delivery: {result['rule']['delivery']}")
    if result.get("artifacts"):
        ctx.echo("Artifacts:")
        for path in result["artifacts"]:
            ctx.echo(f"  - {path}")
    if result["rule"]["delivery"] == DeliveryTarget.STDOUT.value:
        ctx.echo("")
        ctx.echo(result["markdown"], force=True)
    if result.get("delivery_result", {}).get("status") == "error":
        ctx.echo(f"Delivery error: {result['delivery_result']['error']}")
        return 1
    return 0


def run_agent(args, *, ctx: AgentCliContext) -> int:
    """Dispatch the `cortex agent` command group."""
    store_dir = ctx.resolved_store_dir(args.store_dir)

    if args.agent_subcommand == "monitor":
        monitor = ConflictMonitor(
            ConflictMonitorConfig(
                store_dir=store_dir,
                mind_id=getattr(args, "mind", None) or None,
                interval_seconds=args.interval,
                auto_resolve_threshold=args.auto_resolve_threshold,
                interactive=not args.no_prompt,
            )
        )
        if args.once:
            result = monitor.run_cycle()
            if ctx.emit_result(result, args.format) == 0:
                return 0
            ctx.echo(
                f"Detected {result['detected']} conflicts; "
                f"auto-resolved {result['auto_resolved']}; queued {result['queued']}."
            )
            return 0
        controller = ShutdownController()
        thread = threading.Thread(target=monitor.run_forever, daemon=True)
        thread.start()
        with install_shutdown_handlers(controller):
            try:
                while thread.is_alive() and not controller.wait(0.5):
                    continue
            except KeyboardInterrupt:
                controller.request_shutdown("Received KeyboardInterrupt")
            finally:
                monitor.stop()
                thread.join(timeout=args.interval + 2)
        return 0

    dispatcher = ContextDispatcher(store_dir=store_dir, output_root=_output_root(getattr(args, "output_dir", None)))

    if args.agent_subcommand == "compile":
        audience = args.audience or ("recruiter" if args.output == "cv" else "general")
        event = AgentEvent.create(
            EventType.MANUAL_TRIGGER,
            {
                "mind_id": args.mind,
                "audience_id": audience,
                "output_format": args.output,
                "delivery": args.delivery,
                "webhook_url": args.webhook_url,
            },
        )
        result = dispatcher.dispatch(event)
        if ctx.emit_result(result, args.format) == 0:
            return 0
        return _dispatch_text(ctx, result)

    if args.agent_subcommand == "dispatch":
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            return ctx.error(f"Invalid JSON payload: {exc}")
        if not isinstance(payload, dict):
            return ctx.error("dispatch payload must be a JSON object.")
        event = AgentEvent.create(args.event, payload)
        result = dispatcher.dispatch(event)
        if ctx.emit_result(result, args.format) == 0:
            return 0
        return _dispatch_text(ctx, result)

    if args.agent_subcommand == "schedule":
        try:
            delivery = normalize_delivery_target(args.delivery)
            output_format = normalize_output_format(args.output)
        except ValueError as exc:
            return ctx.error(str(exc))
        try:
            result = dispatcher.register_schedule(
                mind_id=args.mind,
                audience_id=args.audience,
                cron_expression=args.cron,
                output_format=output_format,
                delivery=delivery,
                webhook_url=args.webhook_url,
            )
        except ValueError as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(result, args.format) == 0:
            return 0
        schedule = result["schedule"]
        ctx.echo(f"Scheduled {schedule['output_format']} for Mind `{schedule['mind_id']}`")
        ctx.echo(f"  schedule id: {schedule['schedule_id']}")
        ctx.echo(f"  audience: {schedule['audience_id']}")
        ctx.echo(f"  next run: {schedule['next_run_at']}")
        ctx.echo("Next:")
        ctx.echo("  Review schedule status: cortex agent status")
        ctx.echo("  Run the dispatcher immediately if needed: cortex agent compile --mind <id> --output brief")
        return 0

    if args.agent_subcommand == "status":
        review_result: dict[str, Any] | None = None
        if getattr(args, "review", False):
            review_result = review_pending_conflicts(store_dir)
        result = {
            "status": "ok",
            **conflict_status(store_dir),
            **dispatcher_status(store_dir),
        }
        if review_result is not None:
            result["review"] = review_result
        if ctx.emit_result(result, args.format) == 0:
            return 0
        ctx.echo(f"Active monitors: {len(result['active_monitors'])}")
        ctx.echo(f"Pending conflicts: {result['pending_count']}")
        ctx.echo(f"Scheduled dispatches: {result['scheduled_count']}")
        if result["pending_conflicts"]:
            ctx.echo("")
            ctx.echo("Pending conflicts:")
            for item in result["pending_conflicts"][:10]:
                ctx.echo(f"  - [{item['severity']}] {item['summary']}")
        return 0

    return ctx.error("Specify an agent subcommand: monitor, compile, dispatch, schedule, or status")


__all__ = [
    "AgentCliContext",
    "ConflictMonitor",
    "ConflictMonitorConfig",
    "ContextDispatcher",
    "run_agent",
]
