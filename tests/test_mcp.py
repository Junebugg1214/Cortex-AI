import io
import json
from pathlib import Path

from cortex.cli import build_parser, main
from cortex.graph import CortexGraph, Node
from cortex.mcp import CortexMCPServer
from cortex.portable_runtime import load_portability_state, save_canonical_graph, save_portability_state, sync_targets
from cortex.release import API_VERSION, PROJECT_VERSION
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend


def _graph_with_node(node: Node) -> CortexGraph:
    graph = CortexGraph()
    graph.add_node(node)
    return graph


def _initialize(server: CortexMCPServer) -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
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
        "channel_prepare_turn",
        "channel_seed_turn_memory",
    } <= names


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
