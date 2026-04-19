import io
import json
import threading

from cortex.cli import main
from cortex.config import APIKeyConfig
from cortex.graph import CortexGraph, Node
from cortex.minds import init_mind, load_mind_core_graph, remember_on_mind
from cortex.server import make_api_handler
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend
from cortex.webapp import MemoryUIBackend, make_handler


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
    resolved_headers = {
        "Content-Length": str(len(raw)),
        "Host": "127.0.0.1:8766",
    }
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


def _invoke_ui_handler(
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
    handler.client_address = ("127.0.0.1", 8765)
    resolved_headers = {
        "Content-Length": str(len(raw)),
        "Host": "127.0.0.1:8765",
    }
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


def test_security_smoke_api_auth_and_ui_write_guards(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = CortexGraph()
    graph.add_node(Node(id="n1", label="Project Atlas", tags=["active_priorities"], confidence=0.91))
    backend.versions.commit(graph, "baseline")

    api_handler_cls = make_api_handler(
        MemoryService(store_dir=store_dir, backend=backend),
        auth_keys=(
            APIKeyConfig(name="reader", token="reader-token", scopes=("read",), namespaces=("team",)),
            APIKeyConfig(name="writer", token="writer-token", scopes=("write", "index"), namespaces=("team",)),
        ),
    )
    api_unauthorized_status, _, api_unauthorized_body = _invoke_api_handler(
        api_handler_cls,
        path="/v1/query/search?query=atlas&ref=team/atlas&namespace=team",
        method="GET",
    )
    api_authorized_status, _, api_authorized_body = _invoke_api_handler(
        api_handler_cls,
        path="/v1/health",
        method="GET",
        headers={"X-API-Key": "reader-token"},
    )

    assert api_unauthorized_status == 401
    assert "missing API key" in json.loads(api_unauthorized_body)["error"]
    assert api_authorized_status == 200
    assert json.loads(api_authorized_body)["status"] == "ok"

    ui_backend = MemoryUIBackend(store_dir=store_dir, backend=backend)
    session_handler_cls = make_handler(ui_backend)
    session_origin_rejected_status, _, session_origin_rejected_body = _invoke_ui_handler(
        session_handler_cls,
        path="/api/index/rebuild",
        method="POST",
        payload={"ref": "HEAD", "all_refs": False},
        headers={
            "X-Cortex-UI-Session": session_handler_cls._cortex_ui_session_token,
            "Origin": "https://evil.example",
        },
    )

    ui_handler_cls = make_handler(
        ui_backend,
        api_keys=(
            APIKeyConfig(name="reader", token="reader-token", scopes=("read",), namespaces=("team",)),
            APIKeyConfig(name="writer", token="writer-token", scopes=("write", "index"), namespaces=("team",)),
        ),
        allow_local_session=False,
    )
    ui_unauthorized_status, _, ui_unauthorized_body = _invoke_ui_handler(
        ui_handler_cls,
        path="/api/index/rebuild",
        method="POST",
        payload={"ref": "HEAD", "all_refs": False},
    )
    ui_writer_status, _, ui_writer_body = _invoke_ui_handler(
        ui_handler_cls,
        path="/api/index/rebuild",
        method="POST",
        payload={"ref": "HEAD", "all_refs": False},
        headers={"X-API-Key": "writer-token", "Origin": ""},
    )

    assert ui_unauthorized_status == 401
    assert "API key" in json.loads(ui_unauthorized_body)["error"]
    assert session_origin_rejected_status == 403
    assert "Origin matching the current host" in json.loads(session_origin_rejected_body)["error"]
    assert ui_writer_status == 200
    assert json.loads(ui_writer_body)["rebuilt"] == 1


def test_security_smoke_namespace_isolation_for_api(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(CortexGraph(), "main base")
    backend.versions.create_branch("team-a/atlas", switch=True)
    team_a_graph = CortexGraph()
    team_a_graph.add_node(Node(id="n-a", label="Team A Atlas", aliases=["atlas-team-a"], confidence=0.9))
    backend.versions.commit(team_a_graph, "team a base")
    backend.versions.switch_branch("main")

    api_handler_cls = make_api_handler(
        MemoryService(store_dir=store_dir, backend=backend),
        auth_keys=(APIKeyConfig(name="team-a-reader", token="team-a-token", scopes=("read",), namespaces=("team-a",)),),
    )
    allowed_status, _, allowed_body = _invoke_api_handler(
        api_handler_cls,
        path="/v1/query/search",
        method="POST",
        payload={"query": "atlas-team-a", "ref": "team-a/atlas"},
        headers={"X-API-Key": "team-a-token"},
    )
    denied_status, _, denied_body = _invoke_api_handler(
        api_handler_cls,
        path="/v1/query/search",
        method="POST",
        payload={"query": "atlas-team-a", "ref": "team-a/atlas", "namespace": "main"},
        headers={"X-API-Key": "team-a-token"},
    )

    assert allowed_status == 200
    assert json.loads(allowed_body)["results"][0]["node"]["label"] == "Team A Atlas"
    assert denied_status == 403
    assert "outside API key 'team-a-reader' namespace scope" in json.loads(denied_body)["error"]


def test_security_smoke_concurrent_mind_remember_preserves_all_facts(tmp_path):
    store_dir = tmp_path / ".cortex"
    init_mind(store_dir, "marc", kind="person", owner="marc")

    statements = [f"Smoke concurrency fact {index} token-{index:02d}" for index in range(6)]
    errors: list[Exception] = []

    def remember(statement: str) -> None:
        try:
            remember_on_mind(store_dir, "marc", statement=statement)
        except Exception as exc:  # pragma: no cover - defensive for thread collection
            errors.append(exc)

    threads = [threading.Thread(target=remember, args=(statement,)) for statement in statements]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    payload = load_mind_core_graph(store_dir, "marc")
    node_text = "\n".join(
        " ".join(
            filter(
                None,
                [
                    getattr(node, "label", ""),
                    getattr(node, "brief", ""),
                    getattr(node, "full_description", ""),
                ],
            )
        )
        for node in payload["graph"].nodes.values()
    )
    assert payload["fact_count"] >= len(statements)
    for statement in statements:
        assert statement in node_text


def test_security_smoke_doctor_partial_repair_contract(tmp_path, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "config.toml").write_text(
        """
[runtime]
store_dir = "."

[mcp]
namespace = "team"
""".strip(),
        encoding="utf-8",
    )

    rc = main(["mind", "init", "marc", "--kind", "person", "--owner", "marc", "--store-dir", str(project_dir)])
    capsys.readouterr()
    assert rc == 0

    rc = main(["mind", "remember", "marc", "I am Marc Saint-Jour.", "--store-dir", str(project_dir)])
    capsys.readouterr()
    assert rc == 0

    canonical_store = project_dir / ".cortex"
    canonical_store.mkdir()
    (canonical_store / "config.toml").write_text(
        (
            """
[runtime]
store_dir = "."

[mcp]
namespace = "team"
""".strip()
            + "\n"
        ),
        encoding="utf-8",
    )

    rc = main(["doctor", "--store-dir", str(project_dir), "--fix-store", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "partial"
    assert any(action["action"] == "move_store_entry" for action in payload["repair_actions"])
    assert any(conflict["action"] == "move_config" for conflict in payload["repair_conflicts"])
    assert payload["repair_errors"] == []
