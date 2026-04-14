from __future__ import annotations

import io
import json

from cortex.webapp import MemoryUIBackend, UI_HTML, make_handler


def _invoke_handler(handler_cls, *, path: str, method: str = "GET", payload: dict | None = None):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.command = method
    handler.request_version = "HTTP/1.1"
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.client_address = ("127.0.0.1", 8765)
    handler.headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8765", "Content-Type": "application/json"}
    session_token = getattr(handler_cls, "_cortex_ui_session_token", "")
    if session_token:
        handler.headers["X-Cortex-UI-Session"] = session_token
        if method == "POST":
            handler.headers["Origin"] = "http://127.0.0.1:8765"
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


def test_ui_shell_mentions_onboarding_loading_and_shortcuts():
    assert "Create your first Mind" in UI_HTML
    assert "Import from existing source" in UI_HTML
    assert "loading-banner" in UI_HTML
    assert "Keyboard shortcuts" in UI_HTML
    assert "onboarding-wizard" in UI_HTML


def test_ui_backend_exposes_onboarding_state_and_skip(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = MemoryUIBackend(store_dir=store_dir)

    state = backend.onboarding_state()
    skipped = backend.onboarding_skip()

    assert state["status"] == "ok"
    assert state["onboarding"]["step"] == "welcome"
    assert skipped["onboarding"]["status"] == "complete"
    assert skipped["onboarding"]["skipped"] is True


def test_onboarding_create_ingest_and_compile_flow(tmp_path):
    store_dir = tmp_path / ".cortex"
    source = tmp_path / "incident.md"
    source.write_text("Project Atlas launched.", encoding="utf-8")

    backend = MemoryUIBackend(store_dir=store_dir)
    created = backend.onboarding_create_mind(mind_id="ops", label="Ops", owner="tester")
    ingested = backend.onboarding_ingest_source(mind_id="ops", source_kind="file", source_value=str(source))
    compiled = backend.onboarding_compile_output(mind_id="ops", audience_template="executive")

    assert created["status"] == "ok"
    assert ingested["status"] == "ok"
    assert compiled["status"] == "ok"
    assert compiled["onboarding"]["status"] == "complete"


def test_ui_error_envelope_includes_code_and_suggestion(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = MemoryUIBackend(store_dir=store_dir)
    handler_cls = make_handler(backend)

    status, _, body = _invoke_handler(handler_cls, path="/api/does-not-exist", method="GET")
    payload = json.loads(body)

    assert status == 404
    assert payload["status"] == "error"
    assert payload["code"] == "not_found"
    assert payload["suggestion"]
