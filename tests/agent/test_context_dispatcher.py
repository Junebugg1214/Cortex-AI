"""Tests for the proactive context dispatcher."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cortex.agent.context_dispatcher import ContextDispatcher, dispatcher_status, load_schedules, next_cron_run
from cortex.agent.events import AgentEvent, DeliveryTarget, EventType, OutputFormat
from cortex.cli import main
from cortex.graph import CortexGraph, Node
from cortex.minds import _persist_mind_core_graph, init_mind
from cortex.runtime_control import ShutdownController


def _graph_with(*nodes: Node) -> CortexGraph:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    return graph


def _node(
    label: str,
    tag: str,
    *,
    confidence: float = 0.9,
    source: str = "resume",
    timestamp: str = "2026-04-10T12:00:00Z",
    **kwargs,
) -> Node:
    return Node(
        id=kwargs.pop("id", f"{tag}:{label}".replace(" ", "_").lower()),
        label=label,
        tags=kwargs.pop("tags", [tag]),
        confidence=confidence,
        provenance=[{"source": source, "method": "extract", "timestamp": timestamp}],
        **kwargs,
    )


def _seed_mind(store_dir: Path, mind_id: str, graph: CortexGraph) -> None:
    init_mind(store_dir, mind_id, owner="tester")
    _persist_mind_core_graph(
        store_dir,
        mind_id,
        graph,
        message=f"seed {mind_id}",
        source="tests.agent.seed",
    )


def _professional_graph() -> CortexGraph:
    return _graph_with(
        _node(
            "Staff Engineer",
            "professional_context",
            brief="Current title",
            status="active",
            valid_from="2024-01-01T00:00:00Z",
        ),
        _node(
            "Engineer at Acme",
            "work_history",
            brief="2021-2023",
            status="historical",
            valid_from="2021-01-01T00:00:00Z",
            valid_to="2023-12-31T00:00:00Z",
        ),
        _node("Python", "technical_expertise", brief="Primary language"),
        _node("Publication: Distributed Systems Paper", "business_context", brief="Peer-reviewed publication"),
        _node("Certification: AWS Solutions Architect", "business_context", brief="Professional certification"),
        _node("Achievement: launched platform migration", "active_priorities", brief="Major delivery outcome"),
    )


def test_project_stage_changed_resolves_to_onboarding_doc_on_launch(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "project_alpha", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    event = AgentEvent.create(
        EventType.PROJECT_STAGE_CHANGED,
        {"project_id": "project_alpha", "old_stage": "build", "new_stage": "launch"},
    )
    rule = dispatcher.resolve_rule(event)

    assert rule.mind_id == "project_alpha"
    assert rule.output_format is OutputFormat.ONBOARDING_DOC
    assert rule.audience_id == "onboarding"


def test_project_stage_changed_uses_explicit_mind_id_when_present(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "project_alpha", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    event = AgentEvent.create(
        EventType.PROJECT_STAGE_CHANGED,
        {
            "project_id": "external-id",
            "mind_id": "project_alpha",
            "old_stage": "build",
            "new_stage": "launch",
        },
    )
    rule = dispatcher.resolve_rule(event)

    assert rule.mind_id == "project_alpha"


def test_scheduled_review_resolves_to_brief_rule(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    event = AgentEvent.create(
        EventType.SCHEDULED_REVIEW,
        {"mind_id": "personal", "audience_id": "attorney", "cron_expression": "0 9 * * 1"},
    )
    rule = dispatcher.resolve_rule(event)

    assert rule.output_format is OutputFormat.BRIEF
    assert rule.audience_id == "attorney"


def test_fact_threshold_reached_resolves_to_summary_rule(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    event = AgentEvent.create(
        EventType.FACT_THRESHOLD_REACHED,
        {"mind_id": "personal", "fact_count_delta": 25},
    )
    rule = dispatcher.resolve_rule(event)

    assert rule.output_format is OutputFormat.SUMMARY
    assert rule.audience_id == "team"


def test_manual_trigger_resolves_requested_format(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    event = AgentEvent.create(
        EventType.MANUAL_TRIGGER,
        {"mind_id": "personal", "audience_id": "recruiter", "output_format": "cv"},
    )
    rule = dispatcher.resolve_rule(event)

    assert rule.output_format is OutputFormat.CV
    assert rule.audience_id == "recruiter"


def test_compile_cv_writes_markdown_and_json_files(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir, output_root=tmp_path / "output")

    event = AgentEvent.create(
        EventType.MANUAL_TRIGGER,
        {
            "mind_id": "personal",
            "audience_id": "recruiter",
            "output_format": "cv",
            "delivery": "local_file",
        },
    )
    result = dispatcher.dispatch(event)

    assert result["status"] == "ok"
    assert len(result["artifacts"]) == 2
    assert Path(result["artifacts"][0]).name.startswith("cv_")
    assert Path(result["artifacts"][1]).name.startswith("cv_")


def test_cv_output_includes_all_professional_sections(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    markdown, payload = dispatcher.compile_context(
        mind_id="personal",
        audience_id="recruiter",
        output_format=OutputFormat.CV,
    )

    assert "Staff Engineer" in markdown
    assert "Engineer at Acme" in markdown
    assert "Python" in markdown
    assert "Publication: Distributed Systems Paper" in markdown
    assert "Certification: AWS Solutions Architect" in markdown
    assert "Achievement: launched platform migration" in markdown
    assert payload["employment_history"]
    assert payload["skills"]
    assert payload["publications"]
    assert payload["certifications"]
    assert payload["achievements"]


def test_cv_output_includes_source_attribution(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _professional_graph()
    _seed_mind(store_dir, "personal", graph)
    dispatcher = ContextDispatcher(store_dir=store_dir)

    markdown, payload = dispatcher.compile_context(
        mind_id="personal",
        audience_id="recruiter",
        output_format=OutputFormat.CV,
    )

    assert "resume 2026-04-10T12:00:00Z" in markdown
    assert payload["employment_history"][0]["attribution"][0]["source"] == "resume"


def test_cv_output_flags_conflicts_in_professional_history(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node("Engineer", "professional_context", source="resume-a"),
        _node("Designer", "professional_context", source="resume-b", timestamp="2026-04-09T12:00:00Z"),
    )
    _seed_mind(store_dir, "personal", graph)
    dispatcher = ContextDispatcher(store_dir=store_dir)

    markdown, payload = dispatcher.compile_context(
        mind_id="personal",
        audience_id="recruiter",
        output_format=OutputFormat.CV,
    )

    assert "Flags" in markdown
    assert any(flag["type"] == "conflict" for flag in payload["flags"])


def test_cv_output_flags_gaps_in_professional_history(tmp_path):
    store_dir = tmp_path / ".cortex"
    graph = _graph_with(
        _node(
            "Engineer at Acme",
            "work_history",
            status="historical",
            valid_to="2023-12-31T00:00:00Z",
        ),
        _node(
            "Staff Engineer at Beta",
            "work_history",
            status="active",
            valid_from="2024-02-01T00:00:00Z",
        ),
    )
    _seed_mind(store_dir, "personal", graph)
    dispatcher = ContextDispatcher(store_dir=store_dir)

    _, payload = dispatcher.compile_context(
        mind_id="personal",
        audience_id="recruiter",
        output_format=OutputFormat.CV,
    )

    assert any(flag["type"] == "employment_gap" for flag in payload["flags"])


def test_dispatch_local_file_delivery_writes_files(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir, output_root=tmp_path / "output")

    event = AgentEvent.create(
        EventType.MANUAL_TRIGGER,
        {"mind_id": "personal", "audience_id": "team", "output_format": "brief", "delivery": "local_file"},
    )
    result = dispatcher.dispatch(event)

    assert result["delivery_result"]["status"] == "ok"
    assert len(result["artifacts"]) == 2


def test_dispatch_stdout_delivery_keeps_artifacts_empty(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    event = AgentEvent.create(
        EventType.MANUAL_TRIGGER,
        {"mind_id": "personal", "audience_id": "team", "output_format": "summary", "delivery": "stdout"},
    )
    result = dispatcher.dispatch(event)

    assert result["delivery_result"]["status"] == "ok"
    assert result["artifacts"] == []


def test_webhook_delivery_success(monkeypatch, tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    class _Response:
        def read(self) -> bytes:
            return b'{"accepted": true}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=10.0: _Response())

    event = AgentEvent.create(
        EventType.MANUAL_TRIGGER,
        {
            "mind_id": "personal",
            "audience_id": "team",
            "output_format": "summary",
            "delivery": "webhook",
            "webhook_url": "https://example.com/hook",
        },
    )
    result = dispatcher.dispatch(event)

    assert result["status"] == "ok"
    assert result["delivery_result"]["status"] == "ok"


def test_webhook_delivery_failure_is_graceful(monkeypatch, tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    def _fail(request, timeout=10.0):  # noqa: ARG001
        raise urllib.error.URLError("connection refused")

    import urllib.error
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _fail)

    event = AgentEvent.create(
        EventType.MANUAL_TRIGGER,
        {
            "mind_id": "personal",
            "audience_id": "team",
            "output_format": "summary",
            "delivery": "webhook",
            "webhook_url": "https://example.com/hook",
        },
    )
    result = dispatcher.dispatch(event)

    assert result["status"] == "delivery_failed"
    assert result["delivery_result"]["status"] == "error"


def test_register_schedule_persists_next_run(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    result = dispatcher.register_schedule(
        mind_id="personal",
        audience_id="attorney",
        cron_expression="0 9 * * 1",
        output_format=OutputFormat.BRIEF,
        delivery=DeliveryTarget.LOCAL_FILE,
    )

    assert result["status"] == "ok"
    assert load_schedules(store_dir)[0].next_run_at


def test_register_schedule_requires_webhook_url_for_webhook_delivery(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)

    try:
        dispatcher.register_schedule(
            mind_id="personal",
            audience_id="attorney",
            cron_expression="0 9 * * 1",
            output_format=OutputFormat.BRIEF,
            delivery=DeliveryTarget.REST_WEBHOOK,
        )
    except ValueError as exc:
        assert "webhook_url" in str(exc)
    else:
        raise AssertionError("expected register_schedule to reject webhook schedules without a URL")


def test_next_cron_run_returns_expected_weekly_timestamp():
    current = datetime(2026, 4, 11, 13, 0, tzinfo=timezone.utc)
    next_run = next_cron_run("0 9 * * 1", after=current)

    assert next_run == datetime(2026, 4, 13, 9, 0, tzinfo=timezone.utc)


def test_next_cron_run_supports_every_minute():
    current = datetime(2026, 4, 11, 13, 0, tzinfo=timezone.utc)
    next_run = next_cron_run("* * * * *", after=current)

    assert next_run == datetime(2026, 4, 11, 13, 1, tzinfo=timezone.utc)


def test_run_due_schedules_fires_due_schedule(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir, output_root=tmp_path / "output")
    dispatcher.register_schedule(
        mind_id="personal",
        audience_id="team",
        cron_expression="* * * * *",
        output_format=OutputFormat.BRIEF,
    )
    path = store_dir / "agent" / "dispatch_schedules.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schedules"][0]["next_run_at"] = "2026-04-11T12:59:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = dispatcher.run_due_schedules(now=datetime(2026, 4, 11, 13, 0, tzinfo=timezone.utc))

    assert result["dispatched"] == 1
    assert result["results"][0]["artifacts"]


def test_run_due_schedules_skips_future_schedule(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)
    dispatcher.register_schedule(
        mind_id="personal",
        audience_id="team",
        cron_expression="0 9 * * 1",
        output_format=OutputFormat.BRIEF,
    )

    result = dispatcher.run_due_schedules(now=datetime(2026, 4, 11, 13, 0, tzinfo=timezone.utc))

    assert result["dispatched"] == 0


def test_run_due_schedules_returns_error_result_when_dispatch_fails(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)
    dispatcher.register_schedule(
        mind_id="personal",
        audience_id="team",
        cron_expression="* * * * *",
        output_format=OutputFormat.BRIEF,
    )
    path = store_dir / "agent" / "dispatch_schedules.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schedules"][0]["next_run_at"] = "2026-04-11T12:59:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")

    def _boom(event):  # noqa: ARG001
        raise RuntimeError("webhook queue unavailable")

    monkeypatch.setattr(dispatcher, "dispatch", _boom)

    result = dispatcher.run_due_schedules(now=datetime(2026, 4, 11, 13, 0, tzinfo=timezone.utc))
    schedules = load_schedules(store_dir)

    assert result["dispatched"] == 1
    assert result["results"][0]["status"] == "error"
    assert "webhook queue unavailable" in result["results"][0]["error"]
    assert schedules[0].last_run_at


def test_dispatcher_watch_honors_shutdown_controller(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)
    controller = ShutdownController()
    controller.request_shutdown("test stop")
    called = 0

    def _counted_run_due_schedules():
        nonlocal called
        called += 1
        return {"status": "ok", "dispatched": 0, "results": []}

    monkeypatch.setattr(dispatcher, "run_due_schedules", _counted_run_due_schedules)

    dispatcher.watch(interval_seconds=60, shutdown_controller=controller)

    assert called == 0


def test_dispatcher_status_reports_registered_schedules(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)
    dispatcher.register_schedule(
        mind_id="personal",
        audience_id="team",
        cron_expression="0 9 * * 1",
        output_format=OutputFormat.BRIEF,
    )

    status = dispatcher_status(store_dir)

    assert status["scheduled_count"] == 1
    assert status["scheduled_dispatches"][0]["mind_id"] == "personal"


def test_agent_cli_compile_cv_json_contract(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())

    rc = main(
        [
            "agent",
            "compile",
            "--store-dir",
            str(store_dir),
            "--mind",
            "personal",
            "--output",
            "cv",
            "--output-dir",
            str(tmp_path / "output"),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["rule"]["output_format"] == "cv"
    assert payload["artifacts"]


def test_agent_cli_dispatch_project_stage_changed_writes_local_files(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "project_alpha", _professional_graph())

    payload = json.dumps({"project_id": "project_alpha", "old_stage": "build", "new_stage": "launch"})
    rc = main(
        [
            "agent",
            "dispatch",
            "--store-dir",
            str(store_dir),
            "--event",
            "PROJECT_STAGE_CHANGED",
            "--payload",
            payload,
            "--output-dir",
            str(tmp_path / "output"),
            "--format",
            "json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert result["rule"]["output_format"] == "onboarding_doc"
    assert result["artifacts"]


def test_agent_cli_schedule_json_contract(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())

    rc = main(
        [
            "agent",
            "schedule",
            "--store-dir",
            str(store_dir),
            "--mind",
            "personal",
            "--audience",
            "attorney",
            "--cron",
            "0 9 * * 1",
            "--output",
            "brief",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["schedule"]["audience_id"] == "attorney"


def test_agent_cli_status_reports_scheduled_dispatches(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    _seed_mind(store_dir, "personal", _professional_graph())
    dispatcher = ContextDispatcher(store_dir=store_dir)
    dispatcher.register_schedule(
        mind_id="personal",
        audience_id="team",
        cron_expression="0 9 * * 1",
        output_format=OutputFormat.BRIEF,
    )

    rc = main(["agent", "status", "--store-dir", str(store_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["scheduled_count"] == 1
