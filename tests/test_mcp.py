import io
import json

from cortex.cli import build_parser
from cortex.graph import CortexGraph, Node
from cortex.mcp import CortexMCPServer
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
    assert "user-owned" in initialize["result"]["instructions"]
    assert tool_list is not None
    names = {tool["name"] for tool in tool_list["result"]["tools"]}
    assert {"node_upsert", "query_search", "merge_preview", "index_status"} <= names


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
    assert any(tool["name"] == "node_upsert" for tool in lines[1]["result"]["tools"])
