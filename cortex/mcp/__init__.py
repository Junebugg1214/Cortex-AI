from __future__ import annotations

import warnings as _warnings
from importlib import import_module as _import_module
from types import ModuleType as _ModuleType

_TARGET = "cortex.mcp.mcp"
_MESSAGE = "cortex.mcp is deprecated; use cortex.mcp.mcp instead."
_module: _ModuleType | None = None
_public_names: list[str] | None = [
    "API_VERSION",
    "Any",
    "CortexMCPServer",
    "GracefulShutdown",
    "JSONRPC_VERSION",
    "LOGGER",
    "MCPToolRegistry",
    "MCP_SERVER_NAME",
    "MemoryService",
    "OPENAPI_VERSION",
    "PROJECT_VERSION",
    "Path",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "ShutdownController",
    "TextIO",
    "ToolDefinition",
    "annotations",
    "argparse",
    "build_parser",
    "configure_structured_logging",
    "error_envelope",
    "format_startup_diagnostics",
    "get_logger",
    "install_shutdown_handlers",
    "json",
    "jsonrpc_error_data",
    "load_selfhost_config",
    "log_operation",
    "logging",
    "main",
    "sys",
]


def _target_module() -> _ModuleType:
    global _module
    if _module is None:
        _module = _import_module(_TARGET)
    return _module


def _public_exports() -> list[str]:
    return list(_public_names or [])


def __getattr__(name: str) -> object:
    module = _target_module()
    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    if name in _public_exports():
        _warnings.warn(_MESSAGE, DeprecationWarning, stacklevel=2)
        globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_public_exports()))


__all__ = _public_exports()
