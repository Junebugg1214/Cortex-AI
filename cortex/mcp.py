from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from cortex.config import format_startup_diagnostics, load_selfhost_config
from cortex.mcp_tools import MCPToolRegistry, ToolDefinition
from cortex.release import API_VERSION, MCP_SERVER_NAME, OPENAPI_VERSION, PROJECT_VERSION
from cortex.service import MemoryService

JSONRPC_VERSION = "2.0"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-11-05", "2025-11-25")


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, *, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class CortexMCPServer:
    def __init__(
        self,
        *,
        store_dir: str | Path = ".cortex",
        context_file: str | Path | None = None,
        namespace: str | None = None,
        service: MemoryService | None = None,
    ) -> None:
        self.service = service or MemoryService(store_dir=store_dir, context_file=context_file)
        self.store_dir = Path(store_dir)
        self.context_file = Path(context_file).resolve() if context_file else None
        self.namespace = (namespace or "").strip() or None
        self.protocol_version: str | None = None
        self.client_info: dict[str, Any] = {}
        self._initialize_seen = False
        self._client_ready = False
        registry = MCPToolRegistry(service=self.service, effective_namespace=self._effective_namespace)
        self._tools = {tool.name: tool for tool in registry.build()}

    def _instructions(self) -> str:
        namespace_message = (
            f"This session is pinned to namespace '{self.namespace}'."
            if self.namespace
            else "Pass a namespace argument when you want namespace-scoped operations."
        )
        return (
            "Cortex exposes local-first, user-owned AI memory over MCP. "
            "Use portability, node, edge, claim, query, branch, merge, blame, history, index, and prune tools "
            "to work with versioned memory without shelling out. "
            f"Release {PROJECT_VERSION} speaks API {API_VERSION} / OpenAPI {OPENAPI_VERSION}. "
            f"{namespace_message}"
        )

    def _effective_namespace(self, requested: Any | None) -> str | None:
        requested_namespace = str(requested or "").strip() or None
        if self.namespace is None:
            return requested_namespace
        if requested_namespace and requested_namespace != self.namespace:
            raise PermissionError(
                f"This MCP session is pinned to namespace '{self.namespace}', not '{requested_namespace}'."
            )
        return self.namespace

    def _validate_tool_arguments(self, tool: ToolDefinition, arguments: dict[str, Any]) -> None:
        schema = tool.input_schema
        required = schema.get("required", [])
        missing = [name for name in required if name not in arguments]
        if missing:
            joined = ", ".join(sorted(missing))
            raise JsonRpcError(-32602, f"Missing required argument(s) for tool '{tool.name}': {joined}")
        allowed = set(schema.get("properties", {}).keys())
        if not schema.get("additionalProperties", True):
            unknown = sorted(set(arguments) - allowed)
            if unknown:
                joined = ", ".join(unknown)
                raise JsonRpcError(-32602, f"Unknown argument(s) for tool '{tool.name}': {joined}")

    def _success_response(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }

    def _error_response(self, request_id: Any, error: JsonRpcError) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": error.code, "message": error.message},
        }
        if error.data is not None:
            payload["error"]["data"] = error.data
        return payload

    def _tool_result(self, result: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
            "structuredContent": result,
            "isError": is_error,
        }

    def _handle_initialize(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        protocol_version = params.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version.strip():
            raise JsonRpcError(-32602, "initialize requires a string protocolVersion")
        self.protocol_version = (
            protocol_version if protocol_version in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[-1]
        )
        self.client_info = dict(params.get("clientInfo") or {})
        self._initialize_seen = True
        result = {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": MCP_SERVER_NAME, "version": PROJECT_VERSION},
            "instructions": self._instructions(),
        }
        return self._success_response(request_id, result)

    def _handle_tools_list(self, request_id: Any) -> dict[str, Any]:
        return self._success_response(request_id, {"tools": [tool.as_payload() for tool in self._tools.values()]})

    def _handle_tools_call(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise JsonRpcError(-32602, "tools/call requires a string tool name")
        tool = self._tools.get(tool_name)
        if tool is None:
            raise JsonRpcError(-32601, f"Unknown tool: {tool_name}")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, f"Tool '{tool_name}' arguments must be an object")
        self._validate_tool_arguments(tool, arguments)
        try:
            result = tool.handler(arguments)
            return self._success_response(request_id, self._tool_result(result))
        except JsonRpcError:
            raise
        except Exception as exc:
            error_payload = {"status": "error", "error": str(exc), "tool": tool_name}
            return self._success_response(request_id, self._tool_result(error_payload, is_error=True))

    def _dispatch_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if request.get("jsonrpc") != JSONRPC_VERSION:
            raise JsonRpcError(-32600, "Only JSON-RPC 2.0 messages are supported")
        if "method" not in request or not isinstance(request["method"], str):
            raise JsonRpcError(-32600, "Request is missing a string method")

        request_id = request.get("id")
        method = request["method"]
        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "Request params must be an object")

        if method == "initialize":
            return self._handle_initialize(request_id, params)
        if method == "notifications/initialized":
            self._client_ready = True
            return None
        if method == "notifications/cancelled":
            return None
        if method == "ping":
            return None if request_id is None else self._success_response(request_id, {})

        if not self._initialize_seen:
            raise JsonRpcError(-32002, "Cortex MCP server must be initialized before calling tools")

        if method == "tools/list":
            return None if request_id is None else self._handle_tools_list(request_id)
        if method == "tools/call":
            return None if request_id is None else self._handle_tools_call(request_id, params)

        raise JsonRpcError(-32601, f"Method not found: {method}")

    def handle_message(self, message: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(message, list):
            if not message:
                return self._error_response(None, JsonRpcError(-32600, "JSON-RPC batch must not be empty"))
            responses: list[dict[str, Any]] = []
            for item in message:
                if not isinstance(item, dict):
                    responses.append(self._error_response(None, JsonRpcError(-32600, "Batch items must be objects")))
                    continue
                try:
                    response = self._dispatch_request(item)
                except JsonRpcError as exc:
                    response = self._error_response(item.get("id"), exc)
                if response is not None:
                    responses.append(response)
            return responses or None

        if not isinstance(message, dict):
            return self._error_response(None, JsonRpcError(-32600, "JSON-RPC message must be an object"))

        try:
            return self._dispatch_request(message)
        except JsonRpcError as exc:
            return self._error_response(message.get("id"), exc)

    def serve_streams(self, input_stream: TextIO, output_stream: TextIO) -> int:
        for raw_line in input_stream:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                response = self._error_response(None, JsonRpcError(-32700, f"Parse error: {exc.msg}"))
            else:
                response = self.handle_message(payload)
            if response is None:
                continue
            output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
            output_stream.flush()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cortex-mcp", description="Run Cortex as a local MCP tool server over stdio.")
    parser.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    parser.add_argument("--context-file", help="Optional default context graph file")
    parser.add_argument(
        "--namespace",
        help="Optional namespace prefix to pin the MCP session to, such as 'team' or 'team/atlas'",
    )
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
            mcp_namespace=args.namespace,
        )
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    diagnostics = format_startup_diagnostics(config, mode="mcp")
    if args.check:
        print(diagnostics)
        return 0

    server = CortexMCPServer(
        store_dir=config.store_dir,
        context_file=config.context_file,
        namespace=config.mcp_namespace,
    )
    return server.serve_streams(sys.stdin, sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
