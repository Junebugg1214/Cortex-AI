from __future__ import annotations

import io
import json
from pathlib import Path

from cortex.config import APIKeyConfig, load_selfhost_config
from cortex.graph import CortexGraph, Node
from cortex.http_hardening import request_policy_for_mode
from cortex.server import dispatch_api_request, make_api_handler
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend


def _invoke_api_handler(
    handler_cls,
    *,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.command = method
    handler.request_version = "HTTP/1.1"
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.client_address = ("127.0.0.1", 8766)
    resolved_headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8766"}
    if method == "POST":
        resolved_headers["Content-Type"] = "application/json"
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
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    return handler._status, handler._headers, handler.wfile.getvalue().decode("utf-8")


def test_load_selfhost_config_uses_home_cortex_config_when_present(tmp_path: Path):
    home_dir = tmp_path / "home"
    home_config_dir = home_dir / ".cortex"
    home_config_dir.mkdir(parents=True)
    (home_config_dir / "config.toml").write_text("[server]\nport = 9000\n", encoding="utf-8")

    config = load_selfhost_config(env={"HOME": str(home_dir)})

    assert config.config_path == (home_config_dir / "config.toml").resolve()
    assert config.server_port == 9000


def test_hosted_service_request_policy_defaults_to_sixty_per_minute():
    policy = request_policy_for_mode("hosted-service")

    assert policy.rate_limit_per_minute == 60


def test_health_includes_integrity_and_runtime_counts(tmp_path: Path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Atlas", tags=["project"], provenance=[{"source": "doc"}]))
    backend.versions.commit(graph, "seed")

    payload = MemoryService(store_dir=store_dir, backend=backend).health()

    assert payload["graph_integrity"] == "ok"
    assert payload["uptime_seconds"] >= 0
    assert payload["pending_conflicts"] >= 0
    assert payload["scheduled_tasks"] >= 0


def test_dispatch_api_request_returns_structured_auth_error(tmp_path: Path):
    store_dir = tmp_path / ".cortex"
    service = MemoryService(store_dir=store_dir)

    status, payload = dispatch_api_request(
        service,
        method="POST",
        path="/v1/commit",
        payload={"message": "x"},
        auth_keys=(APIKeyConfig(name="writer", token="secret", scopes=("write",), namespaces=("*",)),),
    )

    assert status == 401
    assert payload["code"] == "unauthorized"
    assert payload["suggestion"]


def test_api_handler_validation_errors_include_code_and_suggestion(tmp_path: Path):
    store_dir = tmp_path / ".cortex"
    service = MemoryService(store_dir=store_dir)
    handler_cls = make_api_handler(service)

    status, _, body = _invoke_api_handler(
        handler_cls,
        path="/v1/review",
        method="POST",
        payload={"against": "HEAD"},
        headers={"Content-Type": "text/plain"},
    )
    payload = json.loads(body)

    assert status == 415
    assert payload["code"] == "unsupported_media_type"
    assert payload["suggestion"]
