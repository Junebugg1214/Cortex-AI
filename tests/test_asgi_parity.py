from __future__ import annotations

import asyncio
import io
import json
import shutil
import urllib.parse

from cortex.graph.graph import CortexGraph, Edge, Node
from cortex.service.asgi_app import build_asgi_app
from cortex.service.server import make_api_handler
from cortex.service.service import MemoryService
from cortex.storage import build_sqlite_backend


def _seed_store(store_dir):
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(
        Node(
            id="python",
            label="Python",
            tags=["technical_expertise"],
            confidence=0.9,
            provenance=[{"source": "tests.asgi", "method": "seed"}],
        )
    )
    graph.add_node(
        Node(
            id="atlas",
            label="Project Atlas",
            aliases=["atlas"],
            tags=["active_priorities"],
            confidence=0.95,
            brief="Local memory infrastructure",
            provenance=[{"source": "tests.asgi", "method": "seed"}],
        )
    )
    graph.add_node(
        Node(
            id="sdk",
            label="SDK",
            aliases=["python sdk"],
            tags=["infrastructure"],
            confidence=0.82,
            brief="Python SDK for Cortex",
            provenance=[{"source": "tests.asgi", "method": "seed"}],
        )
    )
    graph.add_edge(
        Edge(
            id="edge1",
            source_id="atlas",
            target_id="sdk",
            relation="requires",
            confidence=0.8,
            provenance=[{"source": "tests.asgi", "method": "seed"}],
        )
    )
    graph.add_edge(
        Edge(
            id="edge2",
            source_id="python",
            target_id="atlas",
            relation="supports",
            confidence=0.75,
            provenance=[{"source": "tests.asgi", "method": "seed"}],
        )
    )
    backend.versions.commit(graph, "baseline")
    return graph.export_v5()


def _service_from_store(store_dir) -> MemoryService:
    return MemoryService(store_dir=store_dir, backend=build_sqlite_backend(store_dir))


def _invoke_stdlib(handler_cls, *, path: str, method: str, payload: dict | None, request_id: str):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.command = method
    handler.request_version = "HTTP/1.1"
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.client_address = ("127.0.0.1", 8766)
    handler.headers = {
        "Content-Length": str(len(raw)),
        "Host": "127.0.0.1:8766",
        "X-Request-ID": request_id,
    }
    if method == "POST":
        handler.headers["Content-Type"] = "application/json"
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
    return handler._status, handler.wfile.getvalue()


async def _invoke_asgi_async(
    app,
    *,
    path: str,
    method: str,
    payload: dict | None,
    request_id: str,
    extra_headers: dict[str, str] | None = None,
):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
    parsed = urllib.parse.urlsplit(path)
    headers = [
        (b"host", b"127.0.0.1:8766"),
        (b"content-length", str(len(raw)).encode("ascii")),
        (b"x-request-id", request_id.encode("ascii")),
    ]
    if method == "POST":
        headers.append((b"content-type", b"application/json"))
    for key, value in (extra_headers or {}).items():
        headers.append((key.lower().encode("ascii"), value.encode("utf-8")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("utf-8"),
        "query_string": parsed.query.encode("utf-8"),
        "headers": headers,
        "client": ("127.0.0.1", 8766),
        "server": ("127.0.0.1", 8766),
    }
    request_sent = False
    messages = []

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        request_sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    status = start["status"]
    response_headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in start.get("headers", [])}
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, response_headers, body


def _invoke_asgi(
    app,
    *,
    path: str,
    method: str,
    payload: dict | None,
    request_id: str,
    extra_headers: dict[str, str] | None = None,
):
    return asyncio.run(
        _invoke_asgi_async(
            app,
            path=path,
            method=method,
            payload=payload,
            request_id=request_id,
            extra_headers=extra_headers,
        )
    )


def test_asgi_app_matches_stdlib_server_for_representative_endpoints(tmp_path):
    seed_dir = tmp_path / "seed" / ".cortex"
    graph_payload = _seed_store(seed_dir)
    requests = [
        ("GET", "/v1/health", None),
        ("GET", "/v1/meta", None),
        ("GET", "/v1/index/status", None),
        ("GET", "/v1/prune/status", None),
        ("GET", "/v1/prune/audit", None),
        ("GET", "/v1/openapi.json", None),
        ("GET", "/v1/agent/status", None),
        ("GET", "/v1/nodes?label=Project%20Atlas", None),
        ("GET", "/v1/nodes/atlas", None),
        ("GET", "/v1/edges?source_id=atlas", None),
        ("GET", "/v1/edges/edge1", None),
        ("GET", "/v1/claims?node_id=atlas", None),
        ("GET", "/v1/branches", None),
        ("GET", "/v1/commits", None),
        ("POST", "/v1/checkout", {"ref": "HEAD"}),
        ("POST", "/v1/diff", {"version_a": "HEAD", "version_b": "HEAD"}),
        ("POST", "/v1/review", {"against": "HEAD", "graph": graph_payload}),
        ("POST", "/v1/query/category", {"tag": "active_priorities"}),
        ("POST", "/v1/query/search", {"query": "atlas", "limit": 5}),
        ("POST", "/v1/query/path", {"from_label": "Python", "to_label": "SDK"}),
    ]

    for index, (method, path, payload) in enumerate(requests, start=1):
        store_dir = tmp_path / f"store-{index}" / ".cortex"
        shutil.copytree(seed_dir, store_dir)
        request_id = f"parity-{index:04d}"

        stdlib_handler = make_api_handler(_service_from_store(store_dir))
        asgi_app = build_asgi_app(_service_from_store(store_dir))

        stdlib_status, stdlib_body = _invoke_stdlib(
            stdlib_handler,
            path=path,
            method=method,
            payload=payload,
            request_id=request_id,
        )
        asgi_status, _asgi_headers, asgi_body = _invoke_asgi(
            asgi_app,
            path=path,
            method=method,
            payload=payload,
            request_id=request_id,
        )

        assert asgi_status == stdlib_status, path
        assert asgi_body == stdlib_body, path


def test_asgi_app_adds_request_id_and_configurable_cors(tmp_path):
    store_dir = tmp_path / ".cortex"
    _seed_store(store_dir)
    app = build_asgi_app(_service_from_store(store_dir), cors_origins=("https://app.example",))

    status, headers, body = _invoke_asgi(
        app,
        path="/v1/health",
        method="GET",
        payload=None,
        request_id="cors-request",
        extra_headers={"origin": "https://app.example"},
    )

    assert status == 200
    assert headers["access-control-allow-origin"] == "https://app.example"
    assert headers["x-request-id"] == "cors-request"
    assert json.loads(body)["request_id"] == "cors-request"
