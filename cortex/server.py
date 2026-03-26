from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from cortex.auth import authorize_api_key
from cortex.config import ALL_SCOPES, APIKeyConfig, format_startup_diagnostics, load_selfhost_config
from cortex.release import API_VERSION, OPENAPI_VERSION, PROJECT_VERSION
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


def _server_url(headers: dict[str, str]) -> str | None:
    normalized = {key.lower(): value for key, value in headers.items()}
    host = normalized.get("host", "").strip()
    if not host:
        return None
    proto = normalized.get("x-forwarded-proto", "http").strip() or "http"
    return f"{proto}://{host}"


def _backend_name(service: MemoryService) -> str:
    module_name = type(service.backend).__module__
    if module_name.endswith(".sqlite"):
        return "sqlite"
    return "filesystem"


def _request_namespace(
    *,
    query: dict[str, list[str]],
    payload: dict[str, Any],
    headers: dict[str, str],
) -> str | None:
    normalized = {key.lower(): value for key, value in headers.items()}
    header_namespace = normalized.get("x-cortex-namespace", "").strip()
    if header_namespace:
        return header_namespace
    payload_namespace = str(payload.get("namespace", "")).strip()
    if payload_namespace:
        return payload_namespace
    return _query_value(query, "namespace")


def _error_payload(exc: Exception) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, FileNotFoundError):
        return 404, {"status": "error", "error": str(exc)}
    if isinstance(exc, PermissionError):
        return 403, {"status": "error", "error": str(exc)}
    if isinstance(exc, ValueError):
        return 400, {"status": "error", "error": str(exc)}
    return 500, {"status": "error", "error": str(exc)}


def _global_route(path: str) -> bool:
    return path in {"/v1/health", "/v1/meta", "/v1/openapi.json"}


def _required_scope(method: str, path: str) -> str:
    read_post_paths = {
        "/v1/checkout",
        "/v1/diff",
        "/v1/review",
        "/v1/blame",
        "/v1/history",
        "/v1/conflicts/detect",
        "/v1/query/category",
        "/v1/query/path",
        "/v1/query/related",
        "/v1/query/search",
        "/v1/query/dsl",
        "/v1/query/nl",
    }
    if path in {"/v1/health", "/v1/meta", "/v1/openapi.json", "/v1/metrics"}:
        return "read"
    if path.startswith("/v1/index/"):
        return "index"
    if path.startswith("/v1/prune"):
        return "prune"
    if path in read_post_paths:
        return "read"
    if method == "GET":
        return "read"
    if path in {"/v1/branches", "/v1/branches/switch"}:
        return "branch"
    if path.startswith("/v1/merge") or path.startswith("/v1/merge-"):
        return "merge"
    if path == "/v1/conflicts/resolve":
        return "write"
    if path in {"/v1/index/rebuild"}:
        return "index"
    if path in {"/v1/prune"}:
        return "prune"
    return "write"


def _legacy_api_keys(api_key: str | None) -> tuple[APIKeyConfig, ...]:
    if not api_key:
        return ()
    return (APIKeyConfig(name="legacy-default", token=api_key, scopes=ALL_SCOPES, namespaces=("*",)),)


def dispatch_api_request(
    service: MemoryService,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    api_key: str | None = None,
    auth_keys: tuple[APIKeyConfig, ...] = (),
) -> tuple[int, dict[str, Any]]:
    headers = headers or {}
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    started = perf_counter()
    request_id = normalized_headers.get("x-request-id", "").strip() or uuid4().hex[:16]

    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    payload = payload or {}
    namespace = _request_namespace(query=query, payload=payload, headers=headers)

    decision = authorize_api_key(
        keys=auth_keys + _legacy_api_keys(api_key),
        headers=headers,
        required_scope=_required_scope(method, parsed.path),
        namespace=namespace,
        namespace_required=not _global_route(parsed.path),
    )
    if not decision.allowed:
        response = {"status": "error", "error": decision.error, "request_id": request_id}
        service.observability.record_request(
            request_id=request_id,
            method=method,
            path=path,
            status=decision.status_code,
            duration_ms=(perf_counter() - started) * 1000,
            namespace=namespace or "",
            backend=_backend_name(service),
            error=decision.error,
        )
        return decision.status_code, response

    namespace = decision.namespace or namespace
    if namespace and "namespace" not in payload:
        payload = {**payload, "namespace": namespace}

    status = 404
    response: dict[str, Any] = {"status": "error", "error": "Not found"}
    try:
        if method == "GET":
            if parsed.path == "/v1/health":
                status, response = 200, service.health()
            elif parsed.path == "/v1/meta":
                status, response = 200, service.meta()
            elif parsed.path == "/v1/metrics":
                status, response = 200, service.metrics(namespace=namespace)
            elif parsed.path == "/v1/index/status":
                status, response = (
                    200,
                    service.index_status(
                        ref=_query_value(query, "ref", "HEAD") or "HEAD",
                        namespace=namespace,
                    ),
                )
            elif parsed.path == "/v1/prune/status":
                status, response = 200, service.prune_status(retention_days=_query_int(query, "retention_days", 7))
            elif parsed.path == "/v1/prune/audit":
                status, response = 200, service.prune_audit(limit=_query_int(query, "limit", 50))
            elif parsed.path == "/v1/openapi.json":
                status, response = 200, service.openapi(server_url=_server_url(headers))
            elif parsed.path == "/v1/nodes":
                status, response = (
                    200,
                    service.lookup_nodes(
                        node_id=_query_value(query, "id", "") or "",
                        canonical_id=_query_value(query, "canonical_id", "") or "",
                        label=_query_value(query, "label", "") or "",
                        ref=_query_value(query, "ref", "HEAD") or "HEAD",
                        limit=_query_int(query, "limit", 10),
                        namespace=namespace,
                    ),
                )
            elif parsed.path.startswith("/v1/nodes/"):
                status, response = (
                    200,
                    service.get_node(
                        node_id=parsed.path[len("/v1/nodes/") :],
                        ref=_query_value(query, "ref", "HEAD") or "HEAD",
                        namespace=namespace,
                    ),
                )
            elif parsed.path == "/v1/edges":
                status, response = (
                    200,
                    service.lookup_edges(
                        edge_id=_query_value(query, "id", "") or "",
                        source_id=_query_value(query, "source_id", "") or "",
                        target_id=_query_value(query, "target_id", "") or "",
                        relation=_query_value(query, "relation", "") or "",
                        ref=_query_value(query, "ref", "HEAD") or "HEAD",
                        limit=_query_int(query, "limit", 10),
                        namespace=namespace,
                    ),
                )
            elif parsed.path.startswith("/v1/edges/"):
                status, response = (
                    200,
                    service.get_edge(
                        edge_id=parsed.path[len("/v1/edges/") :],
                        ref=_query_value(query, "ref", "HEAD") or "HEAD",
                        namespace=namespace,
                    ),
                )
            elif parsed.path == "/v1/claims":
                status, response = (
                    200,
                    service.list_claims(
                        claim_id=_query_value(query, "claim_id", "") or "",
                        node_id=_query_value(query, "node_id", "") or "",
                        canonical_id=_query_value(query, "canonical_id", "") or "",
                        label=_query_value(query, "label", "") or "",
                        source=_query_value(query, "source", "") or "",
                        ref=_query_value(query, "ref", "") or "",
                        version_ref=_query_value(query, "version_ref", "") or "",
                        op=_query_value(query, "op", "") or "",
                        limit=_query_int(query, "limit", 50),
                        namespace=namespace,
                    ),
                )
            elif parsed.path == "/v1/branches":
                status, response = 200, service.list_branches(namespace=namespace)
            elif parsed.path == "/v1/commits":
                status, response = (
                    200,
                    service.log(
                        limit=_query_int(query, "limit", 10),
                        ref=_query_value(query, "ref"),
                        namespace=namespace,
                    ),
                )

        if method == "POST":
            if parsed.path == "/v1/commit":
                status, response = 201, service.commit(**payload)
            elif parsed.path == "/v1/nodes/upsert":
                status, response = 200, service.upsert_node(**payload)
            elif parsed.path == "/v1/nodes/delete":
                status, response = 200, service.delete_node(**payload)
            elif parsed.path == "/v1/edges/upsert":
                status, response = 200, service.upsert_edge(**payload)
            elif parsed.path == "/v1/edges/delete":
                status, response = 200, service.delete_edge(**payload)
            elif parsed.path == "/v1/claims/assert":
                status, response = 200, service.assert_claim(**payload)
            elif parsed.path == "/v1/claims/retract":
                status, response = 200, service.retract_claim(**payload)
            elif parsed.path == "/v1/memory/batch":
                status, response = 200, service.memory_batch(**payload)
            elif parsed.path == "/v1/checkout":
                status, response = 200, service.checkout(**payload)
            elif parsed.path == "/v1/diff":
                status, response = 200, service.diff(**payload)
            elif parsed.path == "/v1/review":
                status, response = 200, service.review(**payload)
            elif parsed.path == "/v1/blame":
                status, response = 200, service.blame(**payload)
            elif parsed.path == "/v1/history":
                status, response = 200, service.history(**payload)
            elif parsed.path == "/v1/conflicts/detect":
                status, response = 200, service.detect_conflicts(**payload)
            elif parsed.path == "/v1/conflicts/resolve":
                status, response = 200, service.resolve_conflict(**payload)
            elif parsed.path == "/v1/index/rebuild":
                status, response = 200, service.index_rebuild(**payload)
            elif parsed.path == "/v1/prune":
                status, response = 200, service.prune(**payload)
            elif parsed.path == "/v1/query/category":
                status, response = 200, service.query_category(**payload)
            elif parsed.path == "/v1/query/path":
                status, response = 200, service.query_path(**payload)
            elif parsed.path == "/v1/query/related":
                status, response = 200, service.query_related(**payload)
            elif parsed.path == "/v1/query/search":
                status, response = 200, service.query_search(**payload)
            elif parsed.path == "/v1/query/dsl":
                status, response = 200, service.query_dsl(**payload)
            elif parsed.path == "/v1/query/nl":
                status, response = 200, service.query_nl(**payload)
            elif parsed.path == "/v1/merge-preview":
                status, response = 200, service.merge_preview(**payload)
            elif parsed.path == "/v1/merge/conflicts":
                status, response = 200, service.merge_conflicts(namespace=namespace)
            elif parsed.path == "/v1/merge/resolve":
                status, response = 200, service.merge_resolve(**payload)
            elif parsed.path == "/v1/merge/commit-resolved":
                status, response = 200, service.merge_commit_resolved(**payload)
            elif parsed.path == "/v1/merge/abort":
                status, response = 200, service.merge_abort(namespace=namespace)
            elif parsed.path == "/v1/branches":
                status, response = 201, service.create_branch(**payload)
            elif parsed.path == "/v1/branches/switch":
                status, response = 200, service.switch_branch(**payload)
    except Exception as exc:  # pragma: no cover - exercised through tests and handler
        status, response = _error_payload(exc)

    response = {**response, "request_id": request_id}
    try:
        index_lag = service.backend.indexing.status(ref="HEAD").get("lag_commits")
    except Exception:
        index_lag = None
    service.observability.record_request(
        request_id=request_id,
        method=method,
        path=path,
        status=status,
        duration_ms=(perf_counter() - started) * 1000,
        namespace=namespace or "",
        backend=_backend_name(service),
        index_lag_commits=index_lag,
        error=response.get("error", "") if status >= 400 else "",
    )
    return status, response


def make_api_handler(
    service: MemoryService,
    *,
    api_key: str | None = None,
    auth_keys: tuple[APIKeyConfig, ...] = (),
):
    class CortexAPIHandler(BaseHTTPRequestHandler):
        server_version = f"CortexAPI/{OPENAPI_VERSION}"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Cortex-Release", PROJECT_VERSION)
            self.send_header("X-Cortex-API-Version", API_VERSION)
            self.send_header("X-Cortex-OpenAPI-Version", OPENAPI_VERSION)
            if payload.get("request_id"):
                self.send_header("X-Request-ID", str(payload["request_id"]))
            release = payload.get("release")
            if isinstance(release, dict):
                contract = release.get("contract")
                if isinstance(contract, dict) and contract.get("hash"):
                    self.send_header("X-Cortex-Contract-Hash", str(contract["hash"]))
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
                auth_keys=auth_keys,
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
                auth_keys=auth_keys,
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
    auth_keys: tuple[APIKeyConfig, ...] = (),
) -> tuple[ThreadingHTTPServer, str]:
    service = MemoryService(store_dir=store_dir, context_file=context_file)
    server = ThreadingHTTPServer((host, port), make_api_handler(service, api_key=api_key, auth_keys=auth_keys))
    actual_host, actual_port = server.server_address
    return server, f"http://{actual_host}:{actual_port}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cortexd", description="Run the local Cortex REST API server.")
    parser.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    parser.add_argument("--context-file", help="Optional default context graph file")
    parser.add_argument("--host", default=None, help="Bind host (default from config or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default from config or 8766)")
    parser.add_argument("--api-key", help="Legacy single API key shortcut")
    parser.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    parser.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_selfhost_config(
            store_dir=args.store_dir,
            context_file=args.context_file,
            config_path=args.config,
            server_host=args.host,
            server_port=args.port,
            api_key=args.api_key,
        )
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    diagnostics = format_startup_diagnostics(config, mode="server")
    if args.check:
        print(diagnostics)
        return 0

    server, url = start_api_server(
        host=config.server_host,
        port=config.server_port,
        store_dir=config.store_dir,
        context_file=config.context_file,
        auth_keys=config.api_keys,
    )
    print(diagnostics)
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
