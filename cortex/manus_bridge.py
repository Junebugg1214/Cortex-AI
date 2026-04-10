from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cortex.auth import authorize_api_key
from cortex.config import (
    RUNTIME_MODES,
    APIKeyConfig,
    format_startup_diagnostics,
    load_selfhost_config,
    validate_runtime_security,
)
from cortex.http_hardening import (
    HTTPRequestPolicy,
    HTTPRequestValidationError,
    InMemoryRateLimiter,
    apply_read_timeout,
    enforce_rate_limit,
    read_json_request,
    request_policy_for_mode,
)
from cortex.mcp import SUPPORTED_PROTOCOL_VERSIONS, CortexMCPServer, JsonRpcError, ToolDefinition

MANUS_BRIDGE_NAME = "cortex-manus"
DEFAULT_MANUS_HOST = "127.0.0.1"
DEFAULT_MANUS_PORT = 8790
DEFAULT_MANUS_PROTOCOL_VERSION = "2024-11-05"
MANUS_MCP_PATHS = ("/", "/mcp")
MANUS_HEALTH_PATHS = ("/health", "/healthz")
DEFAULT_MANUS_TOOLS = (
    "health",
    "meta",
    "portability_context",
    "portability_scan",
    "portability_status",
    "portability_audit",
    "mind_list",
    "mind_status",
    "mind_compose",
    "mind_mounts",
    "pack_list",
    "pack_status",
    "pack_context",
    "pack_query",
    "query_search",
)
OPTIONAL_MANUS_WRITE_TOOLS = (
    "mind_ingest",
    "mind_remember",
    "mind_mount",
    "pack_compile",
    "pack_ask",
    "pack_lint",
    "pack_mount",
)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _normalize_manus_initialize(message: Any, *, protocol_version: str) -> Any:
    if isinstance(message, list):
        return [_normalize_manus_initialize(item, protocol_version=protocol_version) for item in message]
    if not isinstance(message, dict):
        return message
    if str(message.get("method") or "") != "initialize":
        return message
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}
    requested = str(params.get("protocolVersion") or "").strip()
    negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else protocol_version
    if negotiated > protocol_version:
        negotiated = protocol_version
    return {
        **message,
        "params": {
            **params,
            "protocolVersion": negotiated,
        },
    }


def _message_includes_initialize(message: Any) -> bool:
    if isinstance(message, list):
        return any(_message_includes_initialize(item) for item in message)
    if not isinstance(message, dict):
        return False
    return str(message.get("method") or "") == "initialize"


def _auto_initialize_manus_session(server: CortexMCPServer, *, protocol_version: str) -> None:
    if server._initialize_seen:
        return
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": None,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "clientInfo": {
                    "name": MANUS_BRIDGE_NAME,
                    "version": "bridge",
                },
            },
        }
    )
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _tool_scope(tool: ToolDefinition | None) -> str:
    if tool is None:
        return "read"
    annotations = tool.annotations or {}
    return "read" if annotations.get("readOnlyHint", False) else "write"


def _jsonrpc_error_payload(server: CortexMCPServer, message: Any, error: JsonRpcError) -> Any:
    if isinstance(message, list):
        responses: list[dict[str, Any]] = []
        for item in message:
            if isinstance(item, dict):
                responses.append(server._error_response(item.get("id"), error))
        return responses or server._error_response(None, error)
    if isinstance(message, dict):
        return server._error_response(message.get("id"), error)
    return server._error_response(None, error)


def _requested_tool_names(message: Any) -> list[str]:
    if isinstance(message, list):
        names: list[str] = []
        for item in message:
            names.extend(_requested_tool_names(item))
        return names
    if not isinstance(message, dict):
        return []
    if str(message.get("method") or "") != "tools/call":
        return []
    params = message.get("params")
    if not isinstance(params, dict):
        return []
    tool_name = str(params.get("name") or "").strip()
    return [tool_name] if tool_name else []


def _requested_namespace(server: CortexMCPServer, message: Any) -> str | None:
    if server.namespace:
        return server.namespace
    if isinstance(message, list):
        namespaces = {
            namespace for item in message for namespace in [_requested_namespace(server, item)] if namespace is not None
        }
        if len(namespaces) > 1:
            raise ValueError("Batch Manus bridge requests must not span multiple namespaces.")
        return next(iter(namespaces), None)
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    arguments = params.get("arguments")
    if isinstance(arguments, dict):
        namespace = str(arguments.get("namespace") or "").strip()
        if namespace:
            return namespace
    namespace = str(params.get("namespace") or "").strip()
    return namespace or None


def _required_scope(server: CortexMCPServer, message: Any) -> str:
    scopes = [_tool_scope(server._tools.get(name)) for name in _requested_tool_names(message)]
    return "write" if "write" in scopes else "read"


def _tool_accepts_namespace(server: CortexMCPServer, tool_name: str) -> bool:
    tool = server._tools.get(tool_name)
    if tool is None:
        return False
    properties = dict(tool.input_schema.get("properties") or {})
    return "namespace" in properties


def _message_requires_namespace(server: CortexMCPServer, message: Any) -> bool:
    if server.namespace:
        return True
    if isinstance(message, list):
        return any(_message_requires_namespace(server, item) for item in message)
    if not isinstance(message, dict):
        return False
    method = str(message.get("method") or "")
    if method != "tools/call":
        return False
    params = message.get("params")
    if not isinstance(params, dict):
        return False
    tool_name = str(params.get("name") or "").strip()
    return _tool_accepts_namespace(server, tool_name)


def _inject_namespace(server: CortexMCPServer, message: Any, namespace: str | None) -> Any:
    if not namespace or server.namespace or not isinstance(message, dict):
        return message
    if str(message.get("method") or "") != "tools/call":
        return message
    params = message.get("params")
    if not isinstance(params, dict):
        return message
    tool_name = str(params.get("name") or "").strip()
    tool = server._tools.get(tool_name)
    if tool is None:
        return message
    properties = dict(tool.input_schema.get("properties") or {})
    if "namespace" not in properties:
        return message
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return message
    if str(arguments.get("namespace") or "").strip():
        return message
    return {
        **message,
        "params": {
            **params,
            "arguments": {
                **arguments,
                "namespace": namespace,
            },
        },
    }


def _auth_error_payload(server: CortexMCPServer, message: Any, error: str) -> Any:
    return _jsonrpc_error_payload(server, message, JsonRpcError(-32001, error))


def _validate_bridge_security(
    *,
    host: str,
    api_keys: tuple[APIKeyConfig, ...],
    namespace: str | None = None,
    runtime_mode: str = "local-single-user",
    allow_unsafe_bind: bool = False,
    allow_insecure_no_auth: bool = False,
) -> None:
    validate_runtime_security(
        surface="manus",
        host=host,
        runtime_mode=runtime_mode,
        api_keys=api_keys,
        namespace=namespace,
        allow_unsafe_bind=allow_unsafe_bind or allow_insecure_no_auth,
    )


def select_manus_tools(
    server: CortexMCPServer,
    *,
    include_write_tools: bool = False,
    extra_tools: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    requested: list[str] = list(DEFAULT_MANUS_TOOLS)
    if include_write_tools:
        requested.extend(OPTIONAL_MANUS_WRITE_TOOLS)
    requested.extend(str(item).strip() for item in (extra_tools or []) if str(item).strip())

    ordered: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    for name in requested:
        if name in seen:
            continue
        if name not in server._tools:
            unknown.append(name)
            continue
        seen.add(name)
        ordered.append(name)
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown Manus bridge tool(s): {joined}")
    return tuple(ordered)


def configure_manus_toolset(
    server: CortexMCPServer,
    *,
    include_write_tools: bool = False,
    extra_tools: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    allowed = set(
        select_manus_tools(
            server,
            include_write_tools=include_write_tools,
            extra_tools=extra_tools,
        )
    )
    server._tools = {name: tool for name, tool in server._tools.items() if name in allowed}
    return tuple(server._tools.keys())


def dispatch_manus_request(
    server: CortexMCPServer,
    *,
    payload: Any,
    headers: dict[str, str] | None = None,
    api_keys: tuple[APIKeyConfig, ...] = (),
    protocol_version: str = DEFAULT_MANUS_PROTOCOL_VERSION,
) -> tuple[int, Any]:
    headers = headers or {}
    try:
        effective_payload = _normalize_manus_initialize(payload, protocol_version=protocol_version)
        if not _message_includes_initialize(effective_payload):
            _auto_initialize_manus_session(server, protocol_version=protocol_version)
        request_namespace = _requested_namespace(server, effective_payload)
        decision = authorize_api_key(
            keys=api_keys,
            headers=headers,
            required_scope=_required_scope(server, effective_payload),
            namespace=request_namespace,
            namespace_required=request_namespace is not None or _message_requires_namespace(server, effective_payload),
        )
        if not decision.allowed:
            return decision.status_code, _auth_error_payload(server, effective_payload, decision.error)

        if decision.namespace:
            if isinstance(effective_payload, list):
                effective_payload = [_inject_namespace(server, item, decision.namespace) for item in effective_payload]
            else:
                effective_payload = _inject_namespace(server, effective_payload, decision.namespace)

        response = server.handle_message(effective_payload)
        if response is None:
            return 202, {}
        return 200, response
    except ValueError as exc:
        return 400, _jsonrpc_error_payload(server, effective_payload, JsonRpcError(-32602, str(exc)))
    except JsonRpcError as exc:
        return 400, _jsonrpc_error_payload(server, effective_payload, exc)
    except Exception:
        return 500, _jsonrpc_error_payload(
            server,
            effective_payload,
            JsonRpcError(-32603, "Internal Manus bridge error"),
        )


def make_manus_handler(
    server: CortexMCPServer,
    *,
    api_keys: tuple[APIKeyConfig, ...] = (),
    protocol_version: str = DEFAULT_MANUS_PROTOCOL_VERSION,
    request_policy: HTTPRequestPolicy | None = None,
) -> type[BaseHTTPRequestHandler]:
    policy = request_policy or HTTPRequestPolicy()
    rate_limiter = InMemoryRateLimiter(policy.rate_limit_per_minute) if policy.rate_limit_per_minute else None

    class ManusBridgeHandler(BaseHTTPRequestHandler):
        _request_policy = policy
        _rate_limiter = rate_limiter

        def _write_json(self, status: int, payload: Any) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_error(self, status: int, message: str, *, code: int = -32000) -> None:
            self._write_json(status, server._error_response(None, JsonRpcError(code, message)))

        def do_GET(self) -> None:  # noqa: N802
            apply_read_timeout(self, policy=self._request_policy)
            parsed = urlparse(self.path)
            if parsed.path in MANUS_HEALTH_PATHS:
                self._write_json(
                    200,
                    {
                        "status": "ok",
                        "service": MANUS_BRIDGE_NAME,
                        "namespace": server.namespace or "",
                        "tool_count": len(server._tools),
                        "auth_required": bool(api_keys),
                    },
                )
                return
            if parsed.path in MANUS_MCP_PATHS:
                self._write_json(
                    200,
                    {
                        "status": "ok",
                        "service": MANUS_BRIDGE_NAME,
                        "mcp_path": "/mcp",
                        "namespace": server.namespace or "",
                        "tool_count": len(server._tools),
                    },
                )
                return
            self._write_json(404, {"status": "error", "error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            apply_read_timeout(self, policy=self._request_policy)
            if rate_error := enforce_rate_limit(self, limiter=self._rate_limiter, policy=self._request_policy):
                self._write_error(429, rate_error, code=-32029)
                return
            parsed = urlparse(self.path)
            if parsed.path not in MANUS_MCP_PATHS:
                self._write_json(404, {"status": "error", "error": "Not found"})
                return
            try:
                payload = read_json_request(self, policy=self._request_policy, require_object=False)
            except HTTPRequestValidationError as exc:
                code = -32700 if exc.status == 400 and "JSON" in exc.message else -32000
                self._write_error(exc.status, exc.message, code=code)
                return
            status, response = dispatch_manus_request(
                server,
                payload=payload,
                headers={key: value for key, value in self.headers.items()},
                api_keys=api_keys,
                protocol_version=protocol_version,
            )
            self._write_json(status, response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return ManusBridgeHandler


def start_manus_bridge_server(
    *,
    host: str,
    port: int,
    store_dir: str | Path = ".cortex",
    context_file: str | Path | None = None,
    namespace: str | None = None,
    api_keys: tuple[APIKeyConfig, ...] = (),
    include_write_tools: bool = False,
    extra_tools: list[str] | tuple[str, ...] | None = None,
    runtime_mode: str = "local-single-user",
    allow_unsafe_bind: bool = False,
    allow_insecure_no_auth: bool = False,
    protocol_version: str = DEFAULT_MANUS_PROTOCOL_VERSION,
    request_policy: HTTPRequestPolicy | None = None,
) -> tuple[ThreadingHTTPServer, str, tuple[str, ...]]:
    if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        joined = ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
        raise ValueError(f"Unsupported Manus bridge protocol version: {protocol_version}. Expected one of: {joined}")
    _validate_bridge_security(
        host=host,
        api_keys=api_keys,
        namespace=namespace,
        runtime_mode=runtime_mode,
        allow_unsafe_bind=allow_unsafe_bind,
        allow_insecure_no_auth=allow_insecure_no_auth,
    )
    server = CortexMCPServer(store_dir=store_dir, context_file=context_file, namespace=namespace)
    policy = request_policy or request_policy_for_mode(runtime_mode)
    exposed_tools = configure_manus_toolset(
        server,
        include_write_tools=include_write_tools,
        extra_tools=extra_tools,
    )
    httpd = ThreadingHTTPServer(
        (host, port),
        make_manus_handler(
            server,
            api_keys=api_keys,
            protocol_version=protocol_version,
            request_policy=policy,
        ),
    )
    actual_host, actual_port = httpd.server_address
    return httpd, f"http://{actual_host}:{actual_port}/mcp", exposed_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cortex-manus",
        description="Run a Manus-friendly hosted MCP bridge on top of Cortex Minds, Brainpacks, and portable context.",
    )
    parser.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    parser.add_argument("--context-file", help="Optional default context graph file")
    parser.add_argument("--namespace", help="Optional namespace to pin the Manus bridge session to")
    parser.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    parser.add_argument("--host", default=None, help=f"Bind host (default {DEFAULT_MANUS_HOST})")
    parser.add_argument("--port", type=int, default=None, help=f"Bind port (default {DEFAULT_MANUS_PORT})")
    parser.add_argument(
        "--runtime-mode",
        choices=RUNTIME_MODES,
        default=None,
        help="Security posture for HTTP serving (default from config or local-single-user)",
    )
    parser.add_argument(
        "--tool",
        action="append",
        default=[],
        help="Expose an additional Cortex MCP tool by name. Repeatable.",
    )
    parser.add_argument(
        "--allow-write-tools",
        action="store_true",
        help="Expose the curated Manus write-tool set in addition to the default read-oriented toolset.",
    )
    parser.add_argument(
        "--allow-unsafe-bind",
        action="store_true",
        help="Allow a non-loopback bind even when the runtime security contract would normally refuse it.",
    )
    parser.add_argument(
        "--allow-insecure-no-auth",
        dest="allow_unsafe_bind",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--protocol-version",
        default=DEFAULT_MANUS_PROTOCOL_VERSION,
        choices=SUPPORTED_PROTOCOL_VERSIONS,
        help=f"Pin the Manus bridge to a negotiated MCP protocol version (default {DEFAULT_MANUS_PROTOCOL_VERSION}).",
    )
    parser.add_argument("--check", action="store_true", help="Print bridge diagnostics and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_selfhost_config(
            store_dir=args.store_dir,
            context_file=args.context_file,
            config_path=args.config,
            server_host=args.host or DEFAULT_MANUS_HOST,
            server_port=args.port if args.port is not None else DEFAULT_MANUS_PORT,
            runtime_mode=args.runtime_mode,
            mcp_namespace=args.namespace,
        )
        preview_server = CortexMCPServer(
            store_dir=config.store_dir,
            context_file=config.context_file,
            namespace=config.mcp_namespace,
        )
        exposed_tools = select_manus_tools(
            preview_server,
            include_write_tools=args.allow_write_tools,
            extra_tools=args.tool,
        )
        _validate_bridge_security(
            host=config.server_host,
            api_keys=config.api_keys,
            namespace=config.mcp_namespace,
            runtime_mode=config.runtime_mode,
            allow_unsafe_bind=args.allow_unsafe_bind,
        )
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    diagnostics = format_startup_diagnostics(config, mode="server")
    tool_lines = "\n".join(f"    - {name}" for name in exposed_tools)
    if args.check:
        print(
            diagnostics
            + "\n  Bridge:    Manus custom MCP over HTTP (deploy behind HTTPS)\n"
            + f"  MCP path:  /mcp\n  Protocol:  {args.protocol_version}\n  Tool count: {len(exposed_tools)}\n  Tools:\n{tool_lines}"
        )
        return 0

    httpd, url, _ = start_manus_bridge_server(
        host=config.server_host,
        port=config.server_port,
        store_dir=config.store_dir,
        context_file=config.context_file,
        namespace=config.mcp_namespace,
        api_keys=config.api_keys,
        include_write_tools=args.allow_write_tools,
        extra_tools=args.tool,
        runtime_mode=config.runtime_mode,
        allow_unsafe_bind=args.allow_unsafe_bind,
        protocol_version=args.protocol_version,
    )
    print(f"Cortex Manus bridge running at {url}")
    print("Expose this endpoint over HTTPS before adding it to Manus.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        httpd.server_close()
    return 0


__all__ = [
    "DEFAULT_MANUS_TOOLS",
    "OPTIONAL_MANUS_WRITE_TOOLS",
    "MANUS_BRIDGE_NAME",
    "build_parser",
    "configure_manus_toolset",
    "dispatch_manus_request",
    "make_manus_handler",
    "main",
    "select_manus_tools",
    "start_manus_bridge_server",
]


if __name__ == "__main__":  # pragma: no cover - exercised by module CLI smoke tests
    raise SystemExit(main())
