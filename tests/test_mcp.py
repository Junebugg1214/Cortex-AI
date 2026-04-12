import io
import json
from pathlib import Path

from cortex.cli import build_parser, main
from cortex.graph import CortexGraph, Node
from cortex.mcp import CortexMCPServer
from cortex.minds import _persist_mind_core_graph, attach_pack_to_mind, init_mind, load_mind_core_graph
from cortex.packs import compile_pack, ingest_pack, init_pack
from cortex.portable_runtime import load_portability_state, save_canonical_graph, save_portability_state, sync_targets
from cortex.release import API_VERSION, PROJECT_VERSION
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend


def _graph_with_node(node: Node) -> CortexGraph:
    graph = CortexGraph()
    graph.add_node(node)
    return graph


def _graph_with(*nodes: Node) -> CortexGraph:
    graph = CortexGraph()
    for node in nodes:
        graph.add_node(node)
    return graph


def _agent_node(
    label: str,
    tags: str | list[str],
    *,
    confidence: float = 0.9,
    source: str = "resume",
    timestamp: str = "2026-04-10T12:00:00Z",
    **kwargs,
) -> Node:
    tag_list = [tags] if isinstance(tags, str) else list(tags)
    payload = {
        "id": kwargs.pop("id", f"{tag_list[0]}:{label}".replace(" ", "_").lower()),
        "label": label,
        "tags": tag_list,
        "confidence": confidence,
        "provenance": [{"source": source, "method": "extract", "timestamp": timestamp}],
    }
    payload.update(kwargs)
    return Node(**payload)


def _seed_mind(store_dir: Path, mind_id: str, *nodes: Node, namespace: str | None = None) -> None:
    init_mind(store_dir, mind_id, kind="person", owner="marc", namespace=namespace)
    _persist_mind_core_graph(
        store_dir,
        mind_id,
        _graph_with(*nodes),
        message=f"seed {mind_id}",
        source="tests.mcp.agent",
    )


def _initialize(server: CortexMCPServer, *, protocol_version: str = "2025-11-25") -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        }
    )
    assert response is not None
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return response


def _tool_call(server: CortexMCPServer, *, tool: str, arguments: dict | None = None, request_id: int = 2) -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
    )
    assert response is not None
    return response


def test_cli_parser_supports_mcp_subcommand():
    args = build_parser().parse_args(["mcp", "--store-dir", ".cortex", "--namespace", "team"])

    assert args.subcommand == "mcp"
    assert args.store_dir == ".cortex"
    assert args.namespace == "team"


def test_mcp_initialize_and_list_tools(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="n1", label="Project Atlas")), "baseline")

    server = CortexMCPServer(service=MemoryService(store_dir=store_dir, backend=backend))
    initialize = _initialize(server)
    tool_list = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    assert initialize["result"]["protocolVersion"] == "2025-11-25"
    assert initialize["result"]["capabilities"]["tools"]["listChanged"] is False
    assert initialize["result"]["serverInfo"]["version"] == PROJECT_VERSION
    assert "user-owned" in initialize["result"]["instructions"]
    assert API_VERSION in initialize["result"]["instructions"]
    assert tool_list is not None
    names = {tool["name"] for tool in tool_list["result"]["tools"]}
    assert {
        "node_upsert",
        "query_search",
        "merge_preview",
        "index_status",
        "portability_context",
        "portability_scan",
        "portability_status",
        "portability_audit",
        "agent_status",
        "agent_monitor_run",
        "agent_compile",
        "agent_dispatch",
        "agent_schedule",
        "agent_review_conflicts",
        "mind_list",
        "mind_status",
        "mind_ingest",
        "mind_compose",
        "mind_remember",
        "mind_mounts",
        "mind_mount",
        "pack_list",
        "pack_status",
        "pack_context",
        "pack_compile",
        "pack_query",
        "pack_ask",
        "pack_lint",
        "channel_prepare_turn",
        "channel_seed_turn_memory",
    } <= names


def test_mcp_initialize_supports_2024_protocol_clients(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="n1", label="Project Atlas")), "baseline")

    server = CortexMCPServer(service=MemoryService(store_dir=store_dir, backend=backend))
    initialize = _initialize(server, protocol_version="2024-11-05")

    assert initialize["result"]["protocolVersion"] == "2024-11-05"


def _portable_export_path(base: Path) -> Path:
    export_path = base / "chatgpt-export.txt"
    export_path.write_text(
        (
            "I am Marc. "
            "I use Python, FastAPI, Next.js, and CockroachDB. "
            "I prefer direct answers. "
            "I am building Cortex-AI."
        ),
        encoding="utf-8",
    )
    return export_path


def _seed_portability(base: Path, monkeypatch) -> tuple[Path, Path, Path]:
    home_dir = base / "home"
    project_dir = base / "project"
    store_dir = base / ".cortex"
    output_dir = base / "portable"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    export_path = _portable_export_path(base)
    rc = main(
        [
            "portable",
            str(export_path),
            "--to",
            "all",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--output",
            str(output_dir),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    return project_dir, store_dir, output_dir


def _seed_portability_graph(base: Path, monkeypatch) -> tuple[Path, Path, Path]:
    home_dir = base / "home"
    project_dir = base / "project"
    store_dir = base / ".cortex"
    output_dir = base / "portable"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    graph = CortexGraph()
    graph.add_node(
        Node(
            id="n-tech",
            label="Python",
            tags=["technical_expertise"],
            confidence=0.92,
            brief="Primary language: Python",
        )
    )
    graph.add_node(
        Node(
            id="n-name",
            label="Marc",
            tags=["identity"],
            confidence=0.97,
            brief="Name: Marc",
        )
    )
    graph.add_node(
        Node(
            id="n-pref",
            label="Direct answers",
            tags=["communication_preferences"],
            confidence=0.91,
            brief="Prefers direct answers",
        )
    )

    state = load_portability_state(store_dir)
    state, graph_path = save_canonical_graph(store_dir, graph, state=state, graph_path=output_dir / "context.json")
    sync_targets(
        graph,
        targets=["chatgpt", "claude-code"],
        store_dir=store_dir,
        project_dir=str(project_dir),
        output_dir=output_dir,
        graph_path=graph_path,
        policy_name="technical",
        smart=False,
        state=state,
    )
    return project_dir, store_dir, output_dir


def test_mcp_node_round_trip_and_query_search(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    upsert = _tool_call(
        server,
        tool="node_upsert",
        arguments={
            "node": {
                "label": "Project Atlas",
                "aliases": ["atlas"],
                "tags": ["active_priorities"],
                "confidence": 0.93,
            },
            "message": "add atlas via mcp",
        },
    )
    payload = upsert["result"]["structuredContent"]
    node_id = payload["node"]["id"]

    node_get = _tool_call(server, tool="node_get", arguments={"node_id": node_id}, request_id=3)
    search = _tool_call(server, tool="query_search", arguments={"query": "atlas", "limit": 5}, request_id=4)

    assert upsert["result"]["isError"] is False
    assert payload["commit"]["message"] == "add atlas via mcp"
    assert node_get["result"]["structuredContent"]["node"]["label"] == "Project Atlas"
    assert search["result"]["structuredContent"]["results"][0]["node"]["label"] == "Project Atlas"


def test_mcp_mind_tools_round_trip(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store = tmp_path / "openclaw-store"
    home_dir.mkdir()
    project_dir.mkdir()
    downloads_dir = home_dir / "Downloads" / "Exports" / "ChatGPT"
    downloads_dir.mkdir(parents=True)
    (downloads_dir / "custom_instructions.json").write_text(
        json.dumps(
            {
                "what_chatgpt_should_know_about_you": "I use Python and FastAPI.",
                "how_chatgpt_should_respond": "Be concise.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    source.write_text(
        (
            "# Portable AI Memory\n\n"
            "I am Marc Saint-Jour.\n"
            "I am building portable brain-state infrastructure for agents.\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home_dir))
    base_graph = CortexGraph()
    base_graph.add_node(Node(id="n1", label="Marc", tags=["identity"], confidence=0.96))
    state = load_portability_state(store_dir)
    save_canonical_graph(store_dir, base_graph, state=state)
    init_mind(store_dir, "marc", kind="person", owner="marc")
    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)
    attach_pack_to_mind(
        store_dir,
        "marc",
        "ai-memory",
        always_on=True,
        targets=["chatgpt", "claude-code", "codex", "cursor", "hermes", "openclaw"],
    )

    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    list_payload = _tool_call(server, tool="mind_list", request_id=9)["result"]["structuredContent"]
    status_payload = _tool_call(server, tool="mind_status", arguments={"name": "marc"}, request_id=10)["result"][
        "structuredContent"
    ]
    ingest_payload = _tool_call(
        server,
        tool="mind_ingest",
        arguments={"name": "marc", "targets": ["chatgpt"], "project_dir": str(project_dir), "redact_detected": True},
        request_id=11,
    )["result"]["structuredContent"]
    compose_payload = _tool_call(
        server,
        tool="mind_compose",
        arguments={"name": "marc", "target": "chatgpt", "task": "memory strategy", "smart": True, "max_chars": 900},
        request_id=12,
    )["result"]["structuredContent"]
    mount_payload = _tool_call(
        server,
        tool="mind_mount",
        arguments={
            "name": "marc",
            "targets": ["hermes", "claude-code", "codex", "cursor", "openclaw"],
            "task": "support",
            "project_dir": str(project_dir),
            "smart": True,
            "max_chars": 900,
            "openclaw_store_dir": str(openclaw_store),
        },
        request_id=13,
    )["result"]["structuredContent"]
    remember_payload = _tool_call(
        server,
        tool="mind_remember",
        arguments={"name": "marc", "statement": "We use CockroachDB now."},
        request_id=14,
    )["result"]["structuredContent"]
    mounts_payload = _tool_call(
        server,
        tool="mind_mounts",
        arguments={"name": "marc"},
        request_id=15,
    )["result"]["structuredContent"]

    assert list_payload["count"] == 1
    assert list_payload["minds"][0]["mind"] == "marc"
    assert status_payload["mind"] == "marc"
    assert status_payload["manifest"]["kind"] == "person"
    assert status_payload["graph_ref"] == "refs/minds/marc/branches/main"
    assert status_payload["attachment_count"] == 1
    assert status_payload["attached_brainpacks"][0]["pack"] == "ai-memory"
    assert ingest_payload["status"] == "pending_review"
    assert ingest_payload["proposed_source_count"] == 1
    assert ingest_payload["ingested_source_count"] == 0
    assert ingest_payload["selected_sources"][0]["target"] == "chatgpt"
    assert compose_payload["mind"] == "marc"
    assert compose_payload["included_brainpack_count"] == 1
    assert compose_payload["included_brainpacks"][0]["pack"] == "ai-memory"
    assert compose_payload["target"] == "chatgpt"
    assert "Python" not in compose_payload["labels"]
    assert mount_payload["mounted_count"] == 5
    assert remember_payload["mind"] == "marc"
    assert remember_payload["refreshed_mount_count"] == 5
    assert {item["target"] for item in remember_payload["targets"]} == {
        "hermes",
        "claude-code",
        "codex",
        "cursor",
        "openclaw",
    }
    assert mounts_payload["mount_count"] == 5
    assert {item["target"] for item in mounts_payload["mounts"]} == {
        "hermes",
        "claude-code",
        "codex",
        "cursor",
        "openclaw",
    }
    assert (home_dir / ".hermes" / "memories" / "USER.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()
    assert (openclaw_store / "minds.mounted.json").exists()


def test_mcp_namespace_filters_mind_and_pack_tools(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "alpha", kind="person", owner="marc", namespace="team-a")
    init_mind(store_dir, "beta", kind="person", owner="marc", namespace="team-b")
    init_pack(store_dir, "alpha-pack", description="A", owner="marc", namespace="team-a")
    init_pack(store_dir, "beta-pack", description="B", owner="marc", namespace="team-b")

    server = CortexMCPServer(store_dir=store_dir)
    _initialize(server)

    mind_list_payload = _tool_call(server, tool="mind_list", arguments={"namespace": "team-a"}, request_id=91)[
        "result"
    ]["structuredContent"]
    pack_list_payload = _tool_call(server, tool="pack_list", arguments={"namespace": "team-b"}, request_id=92)[
        "result"
    ]["structuredContent"]
    denied_status = _tool_call(
        server,
        tool="mind_status",
        arguments={"name": "beta", "namespace": "team-a"},
        request_id=93,
    )["result"]

    assert mind_list_payload["count"] == 1
    assert mind_list_payload["minds"][0]["mind"] == "alpha"
    assert mind_list_payload["minds"][0]["namespace"] == "team-a"
    assert pack_list_payload["count"] == 1
    assert pack_list_payload["packs"][0]["pack"] == "beta-pack"
    assert pack_list_payload["packs"][0]["namespace"] == "team-b"
    assert denied_status["isError"] is True
    assert "outside namespace 'team-a'" in denied_status["structuredContent"]["error"]


def test_mcp_agent_compile_schedule_and_status_surface(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    _seed_mind(
        store_dir,
        "personal",
        _agent_node("Staff Engineer", "professional_context", brief="Current title", status="active"),
        _agent_node("Python", "technical_expertise", brief="Primary language"),
        _agent_node("Achievement: launched platform migration", "active_priorities", brief="Major outcome"),
    )
    server = CortexMCPServer(service=MemoryService(store_dir=store_dir, backend=backend))
    _initialize(server)

    compile_payload = _tool_call(
        server,
        tool="agent_compile",
        arguments={"mind_id": "personal", "output_format": "cv", "output_dir": str(tmp_path / "output")},
        request_id=120,
    )["result"]["structuredContent"]
    dispatch_payload = _tool_call(
        server,
        tool="agent_dispatch",
        arguments={
            "event": "MANUAL_TRIGGER",
            "payload": {
                "mind_id": "personal",
                "audience_id": "team",
                "output_format": "summary",
            },
            "output_dir": str(tmp_path / "dispatch-output"),
        },
        request_id=121,
    )["result"]["structuredContent"]
    schedule_payload = _tool_call(
        server,
        tool="agent_schedule",
        arguments={
            "mind_id": "personal",
            "audience_id": "team",
            "cron_expression": "0 9 * * 1",
            "output_format": "brief",
        },
        request_id=122,
    )["result"]["structuredContent"]
    status_payload = _tool_call(server, tool="agent_status", request_id=123)["result"]["structuredContent"]

    assert compile_payload["status"] == "ok"
    assert compile_payload["rule"]["output_format"] == "cv"
    assert len(compile_payload["artifacts"]) == 2
    assert dispatch_payload["status"] == "ok"
    assert dispatch_payload["rule"]["output_format"] == "summary"
    assert dispatch_payload["artifacts"]
    assert schedule_payload["schedule"]["mind_id"] == "personal"
    assert status_payload["scheduled_count"] == 1


def test_mcp_agent_monitor_run_and_review_conflicts(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    _seed_mind(
        store_dir,
        "career",
        _agent_node("Engineer", "professional_context", source="resume-a"),
        _agent_node("Designer", "professional_context", source="resume-b", timestamp="2026-04-09T12:00:00Z"),
    )
    server = CortexMCPServer(service=MemoryService(store_dir=store_dir, backend=backend))
    _initialize(server)

    monitor_payload = _tool_call(
        server,
        tool="agent_monitor_run",
        arguments={"mind_id": "career"},
        request_id=124,
    )["result"]["structuredContent"]
    conflict_id = monitor_payload["proposals"][0]["conflict_id"]
    winning_value = monitor_payload["proposals"][0]["candidates"][0]["value"]
    review_payload = _tool_call(
        server,
        tool="agent_review_conflicts",
        arguments={"decisions": [{"conflict_id": conflict_id, "candidate_rank": 1}]},
        request_id=125,
    )["result"]["structuredContent"]
    status_payload = _tool_call(server, tool="agent_status", request_id=126)["result"]["structuredContent"]
    graph_payload = load_mind_core_graph(store_dir, "career")
    labels = sorted(node.label for node in graph_payload["graph"].nodes.values() if "professional_context" in node.tags)

    assert monitor_payload["queued"] == 1
    assert review_payload["resolved"] == 1
    assert status_payload["pending_count"] == 0
    assert labels == [winning_value]


def test_mcp_agent_tools_respect_namespace_filters(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    _seed_mind(store_dir, "alpha", _agent_node("Alpha", "professional_context"), namespace="team-a")
    _seed_mind(store_dir, "beta", _agent_node("Beta", "professional_context"), namespace="team-b")
    service = MemoryService(store_dir=store_dir, backend=backend)
    service.agent_schedule(
        mind_id="alpha",
        audience_id="team",
        cron_expression="0 9 * * 1",
        output_format="brief",
        namespace="team-a",
    )
    service.agent_schedule(
        mind_id="beta",
        audience_id="team",
        cron_expression="0 10 * * 1",
        output_format="brief",
        namespace="team-b",
    )

    server = CortexMCPServer(service=service)
    _initialize(server)

    status_payload = _tool_call(server, tool="agent_status", arguments={"namespace": "team-a"}, request_id=127)[
        "result"
    ]["structuredContent"]
    denied_compile = _tool_call(
        server,
        tool="agent_compile",
        arguments={"mind_id": "beta", "output_format": "summary", "namespace": "team-a"},
        request_id=128,
    )["result"]

    assert status_payload["scheduled_count"] == 1
    assert status_payload["scheduled_dispatches"][0]["mind_id"] == "alpha"
    assert denied_compile["isError"] is True
    assert "outside namespace 'team-a'" in denied_compile["structuredContent"]["error"]


def test_mcp_portability_context_returns_live_target_slice(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    baseline = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "claude-code", "project_dir": str(project_dir), "smart": False},
        request_id=4,
    )
    baseline_payload = baseline["result"]["structuredContent"]

    remember_rc = main(
        [
            "remember",
            "We use CockroachDB now.",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    assert remember_rc == 0

    claude_code = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "claude-code", "project_dir": str(project_dir), "smart": False},
        request_id=5,
    )
    chatgpt = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "chatgpt", "project_dir": str(project_dir), "smart": True},
        request_id=6,
    )
    claude_code_smart = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "claude-code", "project_dir": str(project_dir), "smart": True},
        request_id=7,
    )

    claude_payload = claude_code["result"]["structuredContent"]
    chatgpt_payload = chatgpt["result"]["structuredContent"]
    claude_smart_payload = claude_code_smart["result"]["structuredContent"]
    assert claude_code["result"]["isError"] is False
    assert claude_payload["target"] == "claude-code"
    assert claude_payload["mode"] == "full"
    assert claude_payload["fact_count"] > baseline_payload["fact_count"]
    assert claude_payload["labels"] != baseline_payload["labels"]
    assert "Shared AI Context" in claude_payload["context_markdown"]
    assert claude_code_smart["result"]["isError"] is False
    assert claude_smart_payload["mode"] == "smart"
    assert "Shared AI Context" in claude_smart_payload["context_markdown"]
    assert chatgpt["result"]["isError"] is False
    assert chatgpt_payload["target"] == "chatgpt"
    assert chatgpt_payload["consume_as"] == "custom_instructions"
    assert chatgpt_payload["target_payload"]["combined"]
    assert chatgpt_payload["target_payload"]["respond"]


def test_mcp_brainpack_tools_round_trip(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    imported_store = tmp_path / ".imported"
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    openclaw_store = tmp_path / "openclaw-store"
    source = tmp_path / "brainpack.md"
    bundle = tmp_path / "ai-memory.brainpack.zip"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    source.write_text(
        (
            "# Cortex Brainpacks\n\n"
            "I am Marc.\n"
            "I use Python and FastAPI.\n"
            "I am researching portable AI brain-state layers.\n"
        ),
        encoding="utf-8",
    )
    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")

    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    compile_payload = _tool_call(
        server,
        tool="pack_compile",
        arguments={"name": "ai-memory", "suggest_questions": True, "max_summary_chars": 240},
        request_id=20,
    )["result"]["structuredContent"]
    status_payload = _tool_call(server, tool="pack_status", arguments={"name": "ai-memory"}, request_id=21)["result"][
        "structuredContent"
    ]
    list_payload = _tool_call(server, tool="pack_list", request_id=22)["result"]["structuredContent"]
    context_payload = _tool_call(
        server,
        tool="pack_context",
        arguments={"name": "ai-memory", "target": "chatgpt", "smart": True, "max_chars": 900},
        request_id=23,
    )["result"]["structuredContent"]
    query_payload = _tool_call(
        server,
        tool="pack_query",
        arguments={"name": "ai-memory", "query": "portable AI brain-state layers", "limit": 5},
        request_id=24,
    )["result"]["structuredContent"]
    ask_payload = _tool_call(
        server,
        tool="pack_ask",
        arguments={
            "name": "ai-memory",
            "question": "What does this pack say about portable AI brain-state layers?",
            "output": "note",
            "limit": 5,
            "write_back": True,
        },
        request_id=25,
    )["result"]["structuredContent"]
    lint_payload = _tool_call(
        server,
        tool="pack_lint",
        arguments={"name": "ai-memory"},
        request_id=26,
    )["result"]["structuredContent"]
    mount_payload = _tool_call(
        server,
        tool="pack_mount",
        arguments={
            "name": "ai-memory",
            "targets": ["hermes", "claude-code", "codex", "cursor", "openclaw"],
            "project_dir": str(project_dir),
            "smart": True,
            "max_chars": 900,
            "openclaw_store_dir": str(openclaw_store),
        },
        request_id=27,
    )["result"]["structuredContent"]
    export_payload = _tool_call(
        server,
        tool="pack_export",
        arguments={"name": "ai-memory", "output": str(bundle), "verify": True},
        request_id=28,
    )["result"]["structuredContent"]

    imported_backend = build_sqlite_backend(imported_store)
    imported_service = MemoryService(store_dir=imported_store, backend=imported_backend)
    imported_server = CortexMCPServer(service=imported_service)
    _initialize(imported_server)
    import_payload = _tool_call(
        imported_server,
        tool="pack_import",
        arguments={"archive": str(bundle), "as_name": "ai-memory-copy"},
        request_id=29,
    )["result"]["structuredContent"]

    assert compile_payload["graph_nodes"] >= 3
    assert status_payload["compile_status"] == "compiled"
    assert list_payload["count"] == 1
    assert context_payload["target"] == "chatgpt"
    assert context_payload["fact_count"] >= 1
    assert query_payload["total_matches"] >= 1
    assert ask_payload["artifact_written"] is True
    assert lint_payload["status"] == "ok"
    assert "summary" in lint_payload
    assert {item["target"] for item in mount_payload["targets"]} == {
        "hermes",
        "claude-code",
        "codex",
        "cursor",
        "openclaw",
    }
    assert (home_dir / ".hermes" / "memories" / "USER.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".cursor" / "rules" / "cortex.mdc").exists()
    assert (openclaw_store / "brainpacks.mounted.json").exists()
    assert export_payload["archive"] == str(bundle)
    assert export_payload["verified"] is True
    assert import_payload["pack"] == "ai-memory-copy"
    assert import_payload["compile_status"] == "compiled"


def test_mcp_portability_context_honors_explicit_policy_override(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability_graph(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    technical = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "chatgpt", "project_dir": str(project_dir), "smart": False, "policy": "technical"},
        request_id=10,
    )
    full = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "chatgpt", "project_dir": str(project_dir), "smart": False, "policy": "full"},
        request_id=11,
    )

    technical_payload = technical["result"]["structuredContent"]
    full_payload = full["result"]["structuredContent"]

    assert technical["result"]["isError"] is False
    assert full["result"]["isError"] is False
    assert technical_payload["policy"] == "technical"
    assert full_payload["policy"] == "full"
    assert technical_payload["labels"] == ["Python"]
    assert {"Marc", "Python", "Direct answers"} <= set(full_payload["labels"])


def test_mcp_portability_context_supports_hermes_target(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    hermes = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "hermes", "project_dir": str(project_dir), "smart": True},
        request_id=10,
    )
    payload = hermes["result"]["structuredContent"]

    assert hermes["result"]["isError"] is False
    assert payload["target"] == "hermes"
    assert payload["consume_as"] == "hermes_memory"
    assert payload["target_payload"]["user_text"]
    assert payload["target_payload"]["memory_text"]
    assert payload["target_payload"]["agents_text"]


def test_mcp_portability_context_uses_canonical_updated_at_after_cli_changes(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    state = load_portability_state(store_dir)
    stale_time = "2000-01-01T00:00:00Z"
    state.updated_at = stale_time
    state.targets["chatgpt"].updated_at = stale_time
    save_portability_state(store_dir, state)

    remember_rc = main(
        [
            "remember",
            "We use CockroachDB now.",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
            "--format",
            "json",
        ]
    )
    assert remember_rc == 0

    payload = _tool_call(
        server,
        tool="portability_context",
        arguments={"target": "chatgpt", "project_dir": str(project_dir), "smart": True},
        request_id=12,
    )["result"]["structuredContent"]
    refreshed_state = load_portability_state(store_dir)

    assert payload["updated_at"] != stale_time
    assert payload["updated_at"] == refreshed_state.updated_at


def test_mcp_portability_scan_status_and_audit_report_drift(tmp_path, monkeypatch):
    project_dir, store_dir, output_dir = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    copilot_path = project_dir / ".github" / "copilot-instructions.md"
    copilot_path.write_text(copilot_path.read_text(encoding="utf-8") + "\nMongoDB\n", encoding="utf-8")
    (output_dir / "claude" / "claude_memories.json").unlink()

    scan = _tool_call(
        server,
        tool="portability_scan",
        arguments={"project_dir": str(project_dir)},
        request_id=7,
    )
    status = _tool_call(
        server,
        tool="portability_status",
        arguments={"project_dir": str(project_dir)},
        request_id=8,
    )
    audit = _tool_call(
        server,
        tool="portability_audit",
        arguments={"project_dir": str(project_dir)},
        request_id=9,
    )

    scan_payload = scan["result"]["structuredContent"]
    scan_tools = {tool["target"]: tool for tool in scan_payload["tools"]}
    status_payload = status["result"]["structuredContent"]
    status_map = {item["target"]: item for item in status_payload["issues"]}
    audit_payload = audit["result"]["structuredContent"]

    assert scan["result"]["isError"] is False
    assert scan_payload["scan_mode"] == "metadata_only"
    assert scan_payload["graph_path"] == ""
    assert scan_tools["copilot"]["labels"] == []
    assert scan_tools["copilot"]["paths"] == []
    assert scan_tools["copilot"]["mcp_paths"] == []
    assert status["result"]["isError"] is False
    assert status_map["copilot"]["stale"] is True
    assert status_map["claude"]["stale"] is True
    assert any(
        issue["type"] == "unexpected_context" and issue["target"] == "copilot" for issue in audit_payload["issues"]
    )
    assert any(issue["type"] == "missing_files" and issue["target"] == "claude" for issue in audit_payload["issues"])


def test_mcp_portability_scan_auto_detects_local_mcp_configs(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    (project_dir / ".vscode").mkdir()
    (project_dir / ".vscode" / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "cortex": {"command": "cortex-mcp", "args": ["--config", ".cortex/config.toml"]},
                    "github": {"type": "stdio", "command": "npx", "args": ["-y", "github-mcp"]},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    scan = _tool_call(
        server,
        tool="portability_scan",
        arguments={"project_dir": str(project_dir)},
        request_id=13,
    )["result"]["structuredContent"]
    copilot = {tool["target"]: tool for tool in scan["tools"]}["copilot"]

    assert copilot["configured"] is True
    assert copilot["mcp_server_count"] == 2
    assert copilot["cortex_mcp_configured"] is True
    assert "mcp" in copilot["detection_sources"]
    assert copilot["mcp_paths"] == []
    assert all("path" not in source for source in scan["adoptable_sources"])


def test_mcp_portability_scan_auto_detects_hermes_yaml_config(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    hermes_dir = tmp_path / "home" / ".hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)
    (hermes_dir / "config.yaml").write_text(
        "\n".join(
            [
                "mcp_servers:",
                "  cortex:",
                '    command: "cortex-mcp"',
                "    args:",
                '      - "--config"',
                '      - "/tmp/cortex/config.toml"',
                "  github:",
                '    command: "npx"',
                "    args:",
                '      - "-y"',
                '      - "@modelcontextprotocol/server-github"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    scan = _tool_call(
        server,
        tool="portability_scan",
        arguments={"project_dir": str(project_dir)},
        request_id=14,
    )["result"]["structuredContent"]
    hermes = {tool["target"]: tool for tool in scan["tools"]}["hermes"]

    assert hermes["configured"] is True
    assert hermes["mcp_server_count"] == 2
    assert hermes["cortex_mcp_configured"] is True
    assert hermes["mcp_paths"] == []
    assert all("path" not in source for source in scan["adoptable_sources"])


def test_mcp_portability_scan_rejects_search_roots_argument(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "portability_scan",
                "arguments": {"project_dir": str(project_dir), "search_roots": [str(tmp_path)]},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32602
    assert "Unknown argument(s)" in response["error"]["message"]


def test_mcp_channel_prepare_turn_and_seed_memory_round_trip(tmp_path, monkeypatch):
    project_dir, store_dir, _ = _seed_portability(tmp_path, monkeypatch)
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)
    _initialize(server)

    prepare = _tool_call(
        server,
        tool="channel_prepare_turn",
        arguments={
            "message": {
                "platform": "telegram",
                "workspace_id": "support-bot",
                "conversation_id": "chat-42",
                "user_id": "tg-123",
                "text": "Need help with Next.js.",
                "display_name": "Casey",
                "phone_number": "+1 555 0101",
                "project_dir": str(project_dir),
                "metadata": {"message_id": "msg-1"},
            },
            "target": "chatgpt",
            "smart": True,
        },
        request_id=10,
    )
    turn = prepare["result"]["structuredContent"]["turn"]
    seed = _tool_call(
        server,
        tool="channel_seed_turn_memory",
        arguments={"turn": turn, "source": "pytest.openclaw"},
        request_id=11,
    )

    assert prepare["result"]["isError"] is False
    assert "context_markdown" in turn["context"]
    assert seed["result"]["isError"] is False
    assert seed["result"]["structuredContent"]["status"] == "ok"


def test_mcp_namespace_scoped_session_blocks_cross_namespace_access(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)

    backend.versions.commit(_graph_with_node(Node(id="n1", label="Main Atlas", aliases=["atlas-main"])), "main base")
    backend.versions.create_branch("team/atlas", switch=True)
    backend.versions.commit(_graph_with_node(Node(id="n2", label="Team Atlas", aliases=["atlas-team"])), "team base")
    backend.versions.switch_branch("main")

    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service, namespace="team")
    _initialize(server)

    allowed = _tool_call(
        server,
        tool="query_search",
        arguments={"query": "atlas-team", "ref": "team/atlas", "limit": 5},
        request_id=3,
    )
    blocked_ref = _tool_call(
        server,
        tool="query_search",
        arguments={"query": "atlas-main", "ref": "main", "limit": 5},
        request_id=4,
    )
    blocked_namespace = _tool_call(
        server,
        tool="query_search",
        arguments={"query": "atlas-team", "ref": "team/atlas", "namespace": "main"},
        request_id=5,
    )

    assert allowed["result"]["structuredContent"]["results"][0]["node"]["label"] == "Team Atlas"
    assert blocked_ref["result"]["isError"] is True
    assert "outside 'team'" in blocked_ref["result"]["structuredContent"]["error"]
    assert blocked_namespace["result"]["isError"] is True
    assert "pinned to namespace 'team'" in blocked_namespace["result"]["structuredContent"]["error"]


def test_mcp_stdio_server_reads_and_writes_jsonrpc_lines(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    service = MemoryService(store_dir=store_dir, backend=backend)
    server = CortexMCPServer(service=service)

    input_stream = io.StringIO(
        "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2025-11-25"},
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            ]
        )
        + "\n"
    )
    output_stream = io.StringIO()

    exit_code = server.serve_streams(input_stream, output_stream)
    lines = [json.loads(line) for line in output_stream.getvalue().splitlines()]

    assert exit_code == 0
    assert len(lines) == 2
    assert lines[0]["result"]["serverInfo"]["name"] == "Cortex"
    assert lines[0]["result"]["serverInfo"]["version"] == PROJECT_VERSION
    assert any(tool["name"] == "node_upsert" for tool in lines[1]["result"]["tools"])
