import json
import threading
from http.server import ThreadingHTTPServer

import pytest

pytest.importorskip("nacl.signing")

from cortex.config import APIKeyConfig
from cortex.graph.graph import CortexGraph, Node
from cortex.remote_trust import ensure_store_identity
from cortex.schemas.memory_v1 import RemoteRecord
from cortex.service.server import dispatch_api_request, make_api_handler
from cortex.service.service import MemoryService
from cortex.storage import get_storage_backend


def _start_server(service: MemoryService) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_api_handler(service))
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread, f"http://{host}:{port}"


def _stop_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _graph_bytes(backend, ref: str) -> bytes:
    version_id = backend.versions.resolve_ref(ref)
    assert version_id is not None
    graph = backend.versions.checkout(version_id)
    return json.dumps(graph.export_v5(), sort_keys=True, ensure_ascii=False).encode("utf-8")


def test_http_remote_push_pull_round_trips_signed_bundles(tmp_path):
    store_a = tmp_path / "store-a" / ".cortex"
    store_b = tmp_path / "store-b" / ".cortex"
    identity_a = ensure_store_identity(store_a, name_hint="store-a")
    identity_b = ensure_store_identity(store_b, name_hint="store-b")
    backend_a = get_storage_backend(store_a)
    backend_b = get_storage_backend(store_b)

    graph = CortexGraph()
    graph.add_node(
        Node(
            id="atlas",
            label="Project Atlas",
            tags=["active_priorities"],
            confidence=0.93,
            provenance=[{"source": "test", "source_id": "remote-http"}],
        )
    )
    commit = backend_a.versions.commit(graph, "seed atlas", identity=identity_a)

    service_a = MemoryService(store_dir=store_a, backend=backend_a)
    service_b = MemoryService(store_dir=store_b, backend=backend_b)
    server_a, thread_a, url_a = _start_server(service_a)
    server_b, thread_b, url_b = _start_server(service_b)
    try:
        backend_a.remotes.add_remote(
            RemoteRecord(
                name="origin",
                path=url_b,
                trusted_did=identity_b.did,
                trusted_public_key_b64=identity_b.public_key_b64,
                allowed_namespaces=["main"],
            )
        )
        backend_b.remotes.add_remote(
            RemoteRecord(
                name="store-a",
                path=url_a,
                trusted_did=identity_a.did,
                trusted_public_key_b64=identity_a.public_key_b64,
                allowed_namespaces=["main"],
            )
        )

        pushed = backend_a.remotes.push_remote("origin", branch="main")
        assert pushed["head"] == commit.version_id
        assert pushed["transport"] == "http"
        assert backend_b.versions.resolve_ref("main") == commit.version_id
        assert _graph_bytes(backend_a, "main") == _graph_bytes(backend_b, "main")

        pulled = backend_a.remotes.pull_remote("origin", branch="main", into_branch="roundtrip/main")
        assert pulled["head"] == commit.version_id
        assert pulled["transport"] == "http"
        assert _graph_bytes(backend_a, "roundtrip/main") == _graph_bytes(backend_b, "main")
    finally:
        _stop_server(server_b, thread_b)
        _stop_server(server_a, thread_a)


def test_http_remote_endpoints_require_remote_scope(tmp_path):
    service = MemoryService(store_dir=tmp_path / ".cortex")
    status, response = dispatch_api_request(
        service,
        method="GET",
        path="/v1/remotes/pull?branch=main",
        headers={"Authorization": "Bearer reader-token"},
        auth_keys=(APIKeyConfig(name="reader", token="reader-token", scopes=("read",), namespaces=("*",)),),
    )

    assert status == 403
    assert "scope 'remote'" in response["error"]
