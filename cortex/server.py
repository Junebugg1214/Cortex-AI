from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from cortex.service import MemoryService


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _query_value(values: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    items = values.get(key)
    if not items:
        return default
    return items[0]


def _query_int(values: dict[str, list[str]], key: str, default: int) -> int:
    raw = _query_value(values, key)
    if raw is None or raw == "":
        return default
    return int(raw)


def _query_bool(values: dict[str, list[str]], key: str, default: bool) -> bool:
    raw = _query_value(values, key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _server_url(headers: dict[str, str]) -> str | None:
    host = headers.get("Host", "").strip()
    if not host:
        return None
    proto = headers.get("X-Forwarded-Proto", "http").strip() or "http"
    return f"{proto}://{host}"


def _error_payload(exc: Exception) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, FileNotFoundError):
        return 404, {"status": "error", "error": str(exc)}
    if isinstance(exc, PermissionError):
        return 403, {"status": "error", "error": str(exc)}
    if isinstance(exc, ValueError):
        return 400, {"status": "error", "error": str(exc)}
    return 500, {"status": "error", "error": str(exc)}


def dispatch_api_request(
    service: MemoryService,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    api_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = headers or {}
    header_key = headers.get("X-API-Key", "")
    auth_header = headers.get("Authorization", "")
    bearer_key = auth_header[len("Bearer ") :] if auth_header.startswith("Bearer ") else ""
    if api_key and header_key != api_key and bearer_key != api_key:
        return 401, {"status": "error", "error": "Unauthorized"}

    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    payload = payload or {}
    try:
        if method == "GET":
            if parsed.path == "/v1/health":
                return 200, service.health()
            if parsed.path == "/v1/meta":
                return 200, service.meta()
            if parsed.path == "/v1/index/status":
                return 200, service.index_status(ref=_query_value(query, "ref", "HEAD") or "HEAD")
            if parsed.path == "/v1/openapi.json":
                return 200, service.openapi(server_url=_server_url(headers))
            if parsed.path == "/v1/branches":
                return 200, service.list_branches()
            if parsed.path == "/v1/commits":
                return 200, service.log(limit=_query_int(query, "limit", 10), ref=_query_value(query, "ref"))
        if method == "POST":
            if parsed.path == "/v1/commit":
                return 201, service.commit(**payload)
            if parsed.path == "/v1/checkout":
                return 200, service.checkout(**payload)
            if parsed.path == "/v1/diff":
                return 200, service.diff(**payload)
            if parsed.path == "/v1/review":
                return 200, service.review(**payload)
            if parsed.path == "/v1/blame":
                return 200, service.blame(**payload)
            if parsed.path == "/v1/history":
                return 200, service.history(**payload)
            if parsed.path == "/v1/conflicts/detect":
                return 200, service.detect_conflicts(**payload)
            if parsed.path == "/v1/conflicts/resolve":
                return 200, service.resolve_conflict(**payload)
            if parsed.path == "/v1/index/rebuild":
                return 200, service.index_rebuild(**payload)
            if parsed.path == "/v1/query/category":
                return 200, service.query_category(**payload)
            if parsed.path == "/v1/query/path":
                return 200, service.query_path(**payload)
            if parsed.path == "/v1/query/related":
                return 200, service.query_related(**payload)
            if parsed.path == "/v1/query/search":
                return 200, service.query_search(**payload)
            if parsed.path == "/v1/query/dsl":
                return 200, service.query_dsl(**payload)
            if parsed.path == "/v1/query/nl":
                return 200, service.query_nl(**payload)
            if parsed.path == "/v1/merge-preview":
                return 200, service.merge_preview(**payload)
            if parsed.path == "/v1/merge/conflicts":
                return 200, service.merge_conflicts()
            if parsed.path == "/v1/merge/resolve":
                return 200, service.merge_resolve(**payload)
            if parsed.path == "/v1/merge/commit-resolved":
                return 200, service.merge_commit_resolved(**payload)
            if parsed.path == "/v1/merge/abort":
                return 200, service.merge_abort()
            if parsed.path == "/v1/branches":
                return 201, service.create_branch(**payload)
            if parsed.path == "/v1/branches/switch":
                return 200, service.switch_branch(**payload)
    except Exception as exc:  # pragma: no cover - exercised through tests and handler
        return _error_payload(exc)
    return 404, {"status": "error", "error": "Not found"}


def make_api_handler(service: MemoryService, *, api_key: str | None = None):
    class CortexAPIHandler(BaseHTTPRequestHandler):
        server_version = "CortexAPI/1.0"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def do_GET(self) -> None:  # noqa: N802
            status, response = dispatch_api_request(
                service,
                method="GET",
                path=self.path,
                headers={key: value for key, value in self.headers.items()},
                api_key=api_key,
            )
            self._send_json(response, status=status)

        def do_POST(self) -> None:  # noqa: N802
            status, response = dispatch_api_request(
                service,
                method="POST",
                path=self.path,
                payload=self._read_json(),
                headers={key: value for key, value in self.headers.items()},
                api_key=api_key,
            )
            self._send_json(response, status=status)

    return CortexAPIHandler


def start_api_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    store_dir: str | Path = ".cortex",
    context_file: str | Path | None = None,
    api_key: str | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    service = MemoryService(store_dir=store_dir, context_file=context_file)
    server = ThreadingHTTPServer((host, port), make_api_handler(service, api_key=api_key))
    actual_host, actual_port = server.server_address
    return server, f"http://{actual_host}:{actual_port}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cortexd", description="Run the local Cortex REST API server.")
    parser.add_argument("--store-dir", default=".cortex", help="Storage directory (default: .cortex)")
    parser.add_argument("--context-file", help="Optional default context graph file")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8766, help="Bind port (default: 8766, or 0 for any free port)")
    parser.add_argument("--api-key", help="Optional API key required for requests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server, url = start_api_server(
        host=args.host,
        port=args.port,
        store_dir=args.store_dir,
        context_file=args.context_file,
        api_key=args.api_key,
    )
    print(f"Cortex API running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nCortex API stopped.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
