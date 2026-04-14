from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from cortex.config import APIKeyConfig
from cortex.http_hardening import HTTPRequestPolicy
from cortex.manus_bridge import (
    DEFAULT_MANUS_PROTOCOL_VERSION,
    configure_manus_toolset,
    dispatch_manus_request,
    main,
    make_manus_handler,
    start_manus_bridge_server,
)
from cortex.mcp import CortexMCPServer
from cortex.minds import init_mind, remember_on_mind
from cortex.packs import compile_pack, ingest_pack, init_pack


def _seed_source(path: Path) -> None:
    path.write_text(
        (
            "# Portable AI Memory\n\n"
            "I am Marc Saint-Jour.\n"
            "I use Python, FastAPI, and Cortex.\n"
            "I am building portable brain-state infrastructure for agents.\n"
        ),
        encoding="utf-8",
    )


def _jsonrpc(method: str, *, request_id: int, params: dict | None = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def _invoke_manus_handler(
    handler_cls,
    *,
    path: str = "/mcp",
    payload: dict | list | None = None,
    headers: dict[str, str] | None = None,
):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.command = "POST"
    handler.request_version = "HTTP/1.1"
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.client_address = ("127.0.0.1", 8790)
    resolved_headers = {
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
        "Host": "127.0.0.1:8790",
    }
    if headers:
        resolved_headers.update(headers)
    handler.headers = resolved_headers
    handler._status = 200
    handler._headers = {}

    def send_response(code, message=None):  # noqa: ARG001
        handler._status = code

    def send_header(key, value):
        handler._headers[key] = value

    def end_headers():
        return None

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    handler.do_POST()
    return handler._status, handler._headers, handler.wfile.getvalue().decode("utf-8")


def test_manus_bridge_default_toolset_supports_initialize_list_and_compose(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    remember_on_mind(store_dir, "marc", statement="I am Marc Saint-Jour.")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    initialize_status, initialize_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc("initialize", request_id=1, params={"protocolVersion": "2025-11-25"}),
    )
    list_status, list_payload = dispatch_manus_request(server, payload=_jsonrpc("tools/list", request_id=2))
    compose_status, compose_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc(
            "tools/call",
            request_id=3,
            params={
                "name": "mind_compose",
                "arguments": {
                    "name": "marc",
                    "target": "codex",
                    "task": "support",
                    "smart": True,
                    "max_chars": 900,
                },
            },
        ),
    )

    assert initialize_status == 200
    assert initialize_payload["result"]["serverInfo"]["name"] == "Cortex"
    assert initialize_payload["result"]["protocolVersion"] == DEFAULT_MANUS_PROTOCOL_VERSION
    assert list_status == 200
    tool_names = [tool["name"] for tool in list_payload["result"]["tools"]]
    assert "mind_compose" in tool_names
    assert "mind_remember" not in tool_names
    assert compose_status == 200
    structured = compose_payload["result"]["structuredContent"]
    assert structured["mind"] == "marc"
    assert structured["base_graph_node_count"] >= 1


def test_manus_bridge_auto_initializes_before_tools_list(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    list_status, list_payload = dispatch_manus_request(server, payload=_jsonrpc("tools/list", request_id=21))

    assert list_status == 200
    assert "tools" in list_payload["result"]
    assert server._initialize_seen is True


def test_manus_bridge_auto_initializes_before_tools_call(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    remember_on_mind(store_dir, "marc", statement="I am Marc Saint-Jour.")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    compose_status, compose_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc(
            "tools/call",
            request_id=22,
            params={
                "name": "mind_compose",
                "arguments": {
                    "name": "marc",
                    "target": "codex",
                    "task": "support",
                    "smart": True,
                    "max_chars": 900,
                },
            },
        ),
    )

    assert compose_status == 200
    assert compose_payload["result"]["structuredContent"]["mind"] == "marc"
    assert server._initialize_seen is True


def test_manus_bridge_supports_2024_protocol_clients(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    initialize_status, initialize_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc("initialize", request_id=11, params={"protocolVersion": "2024-11-05"}),
    )

    assert initialize_status == 200
    assert initialize_payload["result"]["protocolVersion"] == "2024-11-05"


def test_manus_bridge_pins_newer_protocol_clients_to_2024_revision(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    initialize_status, initialize_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc("initialize", request_id=12, params={"protocolVersion": "2025-11-25"}),
    )

    assert initialize_status == 200
    assert initialize_payload["result"]["protocolVersion"] == DEFAULT_MANUS_PROTOCOL_VERSION


def test_manus_bridge_pins_unknown_protocol_clients_to_2024_revision(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    initialize_status, initialize_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc("initialize", request_id=13, params={"protocolVersion": "2024-10-07"}),
    )

    assert initialize_status == 200
    assert initialize_payload["result"]["protocolVersion"] == DEFAULT_MANUS_PROTOCOL_VERSION


def test_manus_bridge_can_expose_write_tools_explicitly(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    server._initialize_seen = True

    configure_manus_toolset(server, include_write_tools=True)

    remember_status, remember_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc(
            "tools/call",
            request_id=4,
            params={
                "name": "mind_remember",
                "arguments": {
                    "name": "marc",
                    "statement": "I prefer concise updates.",
                },
            },
        ),
    )
    compose_status, compose_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc(
            "tools/call",
            request_id=5,
            params={
                "name": "mind_compose",
                "arguments": {
                    "name": "marc",
                    "target": "codex",
                    "task": "support",
                    "smart": True,
                    "max_chars": 900,
                },
            },
        ),
    )

    assert remember_status == 200
    assert remember_payload["result"]["structuredContent"]["statement"] == "I prefer concise updates."
    assert compose_status == 200
    assert compose_payload["result"]["structuredContent"]["base_graph_node_count"] >= 1


def test_manus_bridge_read_only_auth_blocks_write_tool(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    server._initialize_seen = True
    configure_manus_toolset(server, include_write_tools=True)

    remember_status, remember_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc(
            "tools/call",
            request_id=6,
            params={
                "name": "mind_remember",
                "arguments": {
                    "name": "marc",
                    "statement": "I prefer concise updates.",
                },
            },
        ),
        api_keys=(APIKeyConfig(name="reader", token="reader-token", scopes=("read",), namespaces=("*",)),),
        headers={"Authorization": "Bearer reader-token"},
    )

    assert remember_status == 403
    assert remember_payload["error"]["code"] == -32001
    assert "does not allow scope 'write'" in remember_payload["error"]["message"]


def test_manus_bridge_batch_namespace_conflict_returns_structured_error(tmp_path):
    store_dir = tmp_path / ".cortex"
    server = CortexMCPServer(store_dir=store_dir)

    status, payload = dispatch_manus_request(
        server,
        payload=[
            _jsonrpc(
                "tools/call",
                request_id=7,
                params={"name": "mind_status", "arguments": {"name": "marc", "namespace": "team-a"}},
            ),
            _jsonrpc(
                "tools/call",
                request_id=8,
                params={"name": "mind_status", "arguments": {"name": "marc", "namespace": "team-b"}},
            ),
        ],
    )

    assert status == 400
    assert [item["id"] for item in payload] == [7, 8]
    assert all(item["error"]["code"] == -32602 for item in payload)
    assert "must not span multiple namespaces" in payload[0]["error"]["message"]


def test_manus_bridge_injects_single_namespace_for_namespace_aware_tool(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "alpha", kind="person", owner="marc", namespace="team-a")
    init_mind(store_dir, "beta", kind="person", owner="marc", namespace="team-b")
    init_pack(store_dir, "alpha-pack", description="A", owner="marc", namespace="team-a")
    init_pack(store_dir, "beta-pack", description="B", owner="marc", namespace="team-b")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    mind_status, mind_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc("tools/call", request_id=31, params={"name": "mind_list", "arguments": {}}),
        api_keys=(APIKeyConfig(name="team-a-reader", token="team-a-token", scopes=("read",), namespaces=("team-a",)),),
        headers={"X-API-Key": "team-a-token"},
    )
    pack_status_code, pack_payload = dispatch_manus_request(
        server,
        payload=_jsonrpc("tools/call", request_id=32, params={"name": "pack_list", "arguments": {}}),
        api_keys=(APIKeyConfig(name="team-b-reader", token="team-b-token", scopes=("read",), namespaces=("team-b",)),),
        headers={"X-API-Key": "team-b-token"},
    )

    assert mind_status == 200
    assert mind_payload["result"]["structuredContent"]["count"] == 1
    assert mind_payload["result"]["structuredContent"]["minds"][0]["mind"] == "alpha"
    assert mind_payload["result"]["structuredContent"]["minds"][0]["namespace"] == "team-a"
    assert pack_status_code == 200
    assert pack_payload["result"]["structuredContent"]["count"] == 1
    assert pack_payload["result"]["structuredContent"]["packs"][0]["pack"] == "beta-pack"
    assert pack_payload["result"]["structuredContent"]["packs"][0]["namespace"] == "team-b"


def test_manus_bridge_requires_explicit_namespace_for_multi_namespace_keys_on_namespace_tools(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "alpha", kind="person", owner="marc", namespace="team-a")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)

    status, payload = dispatch_manus_request(
        server,
        payload=_jsonrpc("tools/call", request_id=33, params={"name": "mind_list", "arguments": {}}),
        api_keys=(
            APIKeyConfig(
                name="multi-reader",
                token="multi-token",
                scopes=("read",),
                namespaces=("team-a", "team-b"),
            ),
        ),
        headers={"Authorization": "Bearer multi-token"},
    )

    assert status == 403
    assert payload["error"]["code"] == -32001
    assert "spans multiple namespaces" in payload["error"]["message"]


def test_manus_bridge_http_server_supports_auth_and_round_trip(tmp_path):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "brainpack.md"
    _seed_source(source)
    init_mind(store_dir, "marc", kind="person", owner="marc")
    remember_on_mind(store_dir, "marc", statement="I am Marc Saint-Jour.")
    init_pack(store_dir, "ai-memory", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, "ai-memory", [str(source)], mode="copy")
    compile_pack(store_dir, "ai-memory", suggest_questions=True, max_summary_chars=240)

    try:
        httpd, url, exposed_tools = start_manus_bridge_server(
            host="127.0.0.1",
            port=0,
            store_dir=store_dir,
            api_keys=(APIKeyConfig(name="reader", token="secret-token", scopes=("read",), namespaces=("*",)),),
        )
    except PermissionError as exc:
        pytest.skip(f"local socket binding is not available in this environment: {exc}")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        health_url = url.removesuffix("/mcp") + "/health"
        with urllib.request.urlopen(health_url, timeout=2.0) as response:
            health_payload = json.loads(response.read().decode("utf-8"))
        assert health_payload["status"] == "ok"
        assert health_payload["tool_count"] == len(exposed_tools)

        unauthorized = urllib.request.Request(
            url,
            data=json.dumps(_jsonrpc("initialize", request_id=1, params={"protocolVersion": "2025-11-25"})).encode(
                "utf-8"
            ),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(unauthorized, timeout=2.0)
        assert exc_info.value.code == 401

        initialize = urllib.request.Request(
            url,
            data=json.dumps(_jsonrpc("initialize", request_id=2, params={"protocolVersion": "2025-11-25"})).encode(
                "utf-8"
            ),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-token",
            },
        )
        with urllib.request.urlopen(initialize, timeout=2.0) as response:
            initialize_payload = json.loads(response.read().decode("utf-8"))
        assert initialize_payload["result"]["serverInfo"]["name"] == "Cortex"
        assert initialize_payload["result"]["protocolVersion"] == DEFAULT_MANUS_PROTOCOL_VERSION

        tool_call = urllib.request.Request(
            url,
            data=json.dumps(
                _jsonrpc(
                    "tools/call",
                    request_id=3,
                    params={
                        "name": "mind_compose",
                        "arguments": {
                            "name": "marc",
                            "target": "codex",
                            "task": "support",
                            "smart": True,
                            "max_chars": 900,
                        },
                    },
                )
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-token",
            },
        )
        with urllib.request.urlopen(tool_call, timeout=2.0) as response:
            tool_payload = json.loads(response.read().decode("utf-8"))
        assert tool_payload["result"]["structuredContent"]["mind"] == "marc"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_manus_bridge_handler_rejects_non_json_content_type(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)
    handler_cls = make_manus_handler(server)

    status, _, body = _invoke_manus_handler(
        handler_cls,
        payload=_jsonrpc("initialize", request_id=41, params={"protocolVersion": "2024-11-05"}),
        headers={"Content-Type": "text/plain"},
    )

    parsed = json.loads(body)
    assert status == 415
    assert "application/json" in parsed["error"]["message"]


def test_manus_bridge_handler_rejects_oversized_body(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)
    handler_cls = make_manus_handler(server, request_policy=HTTPRequestPolicy(max_body_bytes=8))

    status, _, body = _invoke_manus_handler(
        handler_cls,
        payload=_jsonrpc("initialize", request_id=42, params={"protocolVersion": "2024-11-05"}),
    )

    parsed = json.loads(body)
    assert status == 413
    assert "exceeds 8 bytes" in parsed["error"]["message"]


def test_manus_bridge_handler_rate_limits_hosted_requests(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)
    handler_cls = make_manus_handler(server, request_policy=HTTPRequestPolicy(rate_limit_per_minute=1))

    first_status, _, first_body = _invoke_manus_handler(
        handler_cls,
        payload=_jsonrpc("initialize", request_id=43, params={"protocolVersion": "2024-11-05"}),
    )
    second_status, _, second_body = _invoke_manus_handler(
        handler_cls,
        payload=_jsonrpc("tools/list", request_id=44),
    )

    assert first_status == 200
    assert "result" in json.loads(first_body)
    assert second_status == 429
    assert "Too many requests" in json.loads(second_body)["error"]["message"]


def test_manus_bridge_unknown_get_path_returns_404(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")

    try:
        httpd, url, _ = start_manus_bridge_server(
            host="127.0.0.1",
            port=0,
            store_dir=store_dir,
        )
    except PermissionError as exc:
        pytest.skip(f"local socket binding is not available in this environment: {exc}")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        invalid_url = url.removesuffix("/mcp") + "/unknown"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(invalid_url, timeout=2.0)
        assert exc_info.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_manus_bridge_unknown_path_returns_structured_error_payload(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")
    server = CortexMCPServer(store_dir=store_dir)
    configure_manus_toolset(server)
    handler_cls = make_manus_handler(server)

    status, _, body = _invoke_manus_handler(handler_cls, path="/missing", payload=_jsonrpc("tools/list", request_id=45))
    parsed = json.loads(body)

    assert status == 404
    assert parsed["error"]["code"] == -32601
    assert parsed["error"]["data"]["code"] == "method_not_found"
    assert parsed["error"]["data"]["suggestion"]


def test_manus_bridge_rejects_non_loopback_without_auth(tmp_path):
    store_dir = tmp_path / ".cortex"

    with pytest.raises(
        ValueError, match="Refusing to bind the Cortex Manus bridge to a non-loopback host in local-single-user mode"
    ):
        start_manus_bridge_server(host="0.0.0.0", port=0, store_dir=store_dir)


def test_manus_bridge_allows_hosted_service_non_loopback_with_auth(tmp_path):
    store_dir = tmp_path / ".cortex"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[runtime]
store_dir = "{store_dir}"
mode = "hosted-service"

[mcp]
namespace = "team"

[[auth.keys]]
name = "reader"
token = "reader-token"
scopes = ["read"]
namespaces = ["team"]
""".strip(),
        encoding="utf-8",
    )

    rc = main(["--config", str(config_path), "--host", "0.0.0.0", "--check"])

    assert rc == 0


def test_manus_bridge_hosted_service_non_loopback_requires_namespace(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[runtime]
store_dir = "{store_dir}"
mode = "hosted-service"

[[auth.keys]]
name = "reader"
token = "reader-token"
scopes = ["read"]
namespaces = ["team"]
""".strip(),
        encoding="utf-8",
    )

    rc = main(["--config", str(config_path), "--host", "0.0.0.0", "--check"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "without a pinned namespace" in captured.err


def test_manus_bridge_check_outputs_mcp_path_and_tool_count(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    rc = main(["--store-dir", str(store_dir), "--check"])
    captured = capsys.readouterr().out

    assert rc == 0
    assert "Bridge:    Manus custom MCP over HTTP" in captured
    assert "MCP path:  /mcp" in captured
    assert f"Protocol:  {DEFAULT_MANUS_PROTOCOL_VERSION}" in captured
    assert "Tool count:" in captured


def test_manus_bridge_check_rejects_non_loopback_without_auth(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    rc = main(["--store-dir", str(store_dir), "--host", "0.0.0.0", "--check"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Refusing to bind the Cortex Manus bridge to a non-loopback host in local-single-user mode" in captured.err


def test_manus_bridge_check_allows_explicit_insecure_override(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    rc = main(["--store-dir", str(store_dir), "--host", "0.0.0.0", "--check", "--allow-insecure-no-auth"])
    captured = capsys.readouterr().out

    assert rc == 0
    assert "Bridge:    Manus custom MCP over HTTP" in captured


def test_manus_bridge_module_cli_check_outputs_diagnostics(tmp_path):
    store_dir = tmp_path / ".cortex"

    result = subprocess.run(
        [sys.executable, "-m", "cortex.manus_bridge", "--store-dir", str(store_dir), "--check"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Bridge:    Manus custom MCP over HTTP" in result.stdout
    assert "MCP path:  /mcp" in result.stdout
