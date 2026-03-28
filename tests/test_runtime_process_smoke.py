import json
import os
import select
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from cortex.cli import main
from cortex.graph import CortexGraph, Edge, Node
from cortex.portable_runtime import load_portability_state, save_portability_state
from cortex.storage import build_sqlite_backend


def _seed_store(store_dir: Path) -> None:
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(
        Node(
            id="atlas",
            label="Project Atlas",
            aliases=["atlas"],
            tags=["active_priorities"],
            confidence=0.93,
            brief="User-owned memory runtime",
        )
    )
    graph.add_node(
        Node(
            id="sdk",
            label="Python SDK",
            aliases=["python sdk"],
            tags=["infrastructure"],
            confidence=0.84,
            brief="Programmatic Cortex client",
        )
    )
    graph.add_node(
        Node(
            id="mcp",
            label="MCP Server",
            aliases=["mcp"],
            tags=["integration"],
            confidence=0.85,
            brief="Tool interface for AI runtimes",
        )
    )
    graph.add_edge(Edge(id="e1", source_id="sdk", target_id="atlas", relation="supports", confidence=0.78))
    graph.add_edge(Edge(id="e2", source_id="atlas", target_id="mcp", relation="exposed_via", confidence=0.81))
    backend.versions.commit(graph, "seed runtime smoke")


def _seed_portability_store(base: Path, monkeypatch) -> tuple[Path, Path]:
    home_dir = base / "home"
    project_dir = base / "project"
    store_dir = base / ".cortex"
    output_dir = base / "portable"
    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    (project_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "runtime-portability",
                "dependencies": {"next": "14.1.0", "react": "18.2.0"},
                "devDependencies": {"vitest": "1.5.0"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    export_path = base / "chatgpt-export.txt"
    export_path.write_text(
        (
            "My name is Marc. "
            "I use Python, FastAPI, and Next.js. "
            "I prefer direct answers. "
            "I am building runtime-portability."
        ),
        encoding="utf-8",
    )
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
    return project_dir, store_dir


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            pytest.skip(f"local socket binding is not available in this environment: {exc}")
        return int(sock.getsockname()[1])


def _wait_for_http(url: str, *, timeout: float = 10.0) -> dict | str:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                body = response.read().decode("utf-8")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> dict | str:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=2.0) as response:
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _spawn_logged_process(*args: str, log_path: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, *args],
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    process._codex_log_handle = handle  # type: ignore[attr-defined]
    return process


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    handle = getattr(process, "_codex_log_handle", None)
    if handle is not None:
        handle.close()


def _jsonrpc(proc: subprocess.Popen[str], message: dict, *, timeout: float = 5.0) -> dict:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.1)
        if not ready:
            if proc.poll() is not None:
                stderr = proc.stderr.read() if proc.stderr is not None else ""
                raise AssertionError(f"MCP process exited early with code {proc.returncode}: {stderr}")
            continue
        raw = proc.stdout.readline()
        if not raw:
            continue
        return json.loads(raw)
    raise AssertionError(f"Timed out waiting for JSON-RPC response to {message['method']}")


def test_cortexd_process_serves_real_http_requests(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_store(store_dir)
    port = _free_port()
    log_path = tmp_path / "cortexd.log"
    process = _spawn_logged_process(
        "-m",
        "cortex.server",
        "--store-dir",
        str(store_dir),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        log_path=log_path,
    )
    try:
        health = _wait_for_http(f"http://127.0.0.1:{port}/v1/health")
        meta = _wait_for_http(f"http://127.0.0.1:{port}/v1/meta")
        search = _request_json(
            f"http://127.0.0.1:{port}/v1/query/search",
            method="POST",
            payload={"query": "atlas", "limit": 5},
        )
        metrics = _wait_for_http(f"http://127.0.0.1:{port}/v1/metrics")
    finally:
        _stop_process(process)

    logs = log_path.read_text(encoding="utf-8")

    assert health["status"] == "ok"
    assert meta["backend"] == "sqlite"
    assert search["results"][0]["node"]["label"] == "Project Atlas"
    assert metrics["requests_total"] >= 1
    assert "Cortex API running at http://127.0.0.1:" in logs
    assert "Cortex server diagnostics:" in logs


def test_web_ui_process_serves_real_control_plane_requests(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_store(store_dir)
    port = _free_port()
    log_path = tmp_path / "ui.log"
    process = _spawn_logged_process(
        "-m",
        "cortex.cli",
        "ui",
        "--store-dir",
        str(store_dir),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        log_path=log_path,
    )
    try:
        html = _wait_for_http(f"http://127.0.0.1:{port}/")
        meta = _wait_for_http(f"http://127.0.0.1:{port}/api/meta")
        health = _wait_for_http(f"http://127.0.0.1:{port}/api/health")
        index = _wait_for_http(f"http://127.0.0.1:{port}/api/index/status?ref=HEAD")
    finally:
        _stop_process(process)

    logs = log_path.read_text(encoding="utf-8")

    assert isinstance(html, str)
    assert "Cortex Infra" in html
    assert meta["backend"] == "sqlite"
    assert health["status"] == "ok"
    assert index["persistent"] is True
    assert "Cortex UI running at http://127.0.0.1:" in logs


def test_cortex_mcp_process_serves_real_stdio_requests(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_store(store_dir)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "cortex.mcp", "--store-dir", str(store_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    try:
        initialize = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        tools = _jsonrpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        search = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "query_search", "arguments": {"query": "atlas", "limit": 5}},
            },
        )
        node_get = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "node_get", "arguments": {"node_id": "atlas"}},
            },
        )
    finally:
        if process.stdin is not None:
            process.stdin.close()
        _stop_process(process)

    assert initialize["result"]["serverInfo"]["name"] == "Cortex"
    assert any(tool["name"] == "query_search" for tool in tools["result"]["tools"])
    assert search["result"]["structuredContent"]["results"][0]["node"]["label"] == "Project Atlas"
    assert node_get["result"]["structuredContent"]["node"]["label"] == "Project Atlas"


def test_cortex_mcp_process_serves_live_portability_after_cli_changes(tmp_path, monkeypatch):
    project_dir, store_dir = _seed_portability_store(tmp_path, monkeypatch)
    state = load_portability_state(store_dir)
    stale_time = "2000-01-01T00:00:00Z"
    state.updated_at = stale_time
    state.targets["chatgpt"].updated_at = stale_time
    save_portability_state(store_dir, state)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "cortex.mcp", "--store-dir", str(store_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    try:
        _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()

        before = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "portability_context",
                    "arguments": {"target": "chatgpt", "project_dir": str(project_dir), "smart": True},
                },
            },
        )
        full = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "portability_context",
                    "arguments": {
                        "target": "chatgpt",
                        "project_dir": str(project_dir),
                        "smart": False,
                        "policy": "full",
                    },
                },
            },
        )
        technical = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "portability_context",
                    "arguments": {
                        "target": "chatgpt",
                        "project_dir": str(project_dir),
                        "smart": False,
                        "policy": "technical",
                    },
                },
            },
        )

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

        after = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "portability_context",
                    "arguments": {"target": "chatgpt", "project_dir": str(project_dir), "smart": True},
                },
            },
        )
    finally:
        if process.stdin is not None:
            process.stdin.close()
        _stop_process(process)

    before_payload = before["result"]["structuredContent"]
    after_payload = after["result"]["structuredContent"]
    full_payload = full["result"]["structuredContent"]
    technical_payload = technical["result"]["structuredContent"]

    assert full_payload["policy"] == "full"
    assert technical_payload["policy"] == "technical"
    assert set(full_payload["labels"]) > set(technical_payload["labels"])
    assert before_payload["updated_at"] == stale_time
    assert after_payload["updated_at"] != stale_time


def test_cortex_mcp_process_handles_channel_prepare_and_seed(tmp_path, monkeypatch):
    project_dir, store_dir = _seed_portability_store(tmp_path, monkeypatch)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "cortex.mcp", "--store-dir", str(store_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    try:
        _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()

        prepare = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "channel_prepare_turn",
                    "arguments": {
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
                },
            },
        )
        turn = prepare["result"]["structuredContent"]["turn"]
        seed = _jsonrpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "channel_seed_turn_memory",
                    "arguments": {"turn": turn, "source": "pytest.process"},
                },
            },
        )
    finally:
        if process.stdin is not None:
            process.stdin.close()
        _stop_process(process)

    assert prepare["result"]["structuredContent"]["turn"]["context"]["status"] == "ok"
    assert seed["result"]["structuredContent"]["status"] == "ok"
