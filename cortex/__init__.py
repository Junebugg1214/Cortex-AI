"""Cortex — local AI identity and memory toolkit."""

from __future__ import annotations

import warnings as _warnings
from importlib import import_module as _import_module

from cortex.release import PROJECT_VERSION

__version__ = PROJECT_VERSION

_EXPORTS = {
    "API_VERSION": "cortex.release",
    "OPENAPI_VERSION": "cortex.release",
    "ChannelContextBridge": "cortex.channel_runtime",
    "ChannelMessage": "cortex.channel_runtime",
    "ChannelWriteBatch": "cortex.channel_runtime",
    "GenericChannelAdapter": "cortex.channel_runtime",
    "HERMES_PROFILE": "cortex.channel_runtime",
    "OPENCLAW_PROFILE": "cortex.channel_runtime",
    "MemorySession": "cortex.session",
    "branch_name_for_task": "cortex.session",
    "channel_write_plan": "cortex.channel_runtime",
    "render_search_context": "cortex.session",
}

_LAZY_COMPAT_SUBMODULES = {
    "adapters",
    "auth",
    "centrality",
    "claims",
    "context",
    "contradictions",
    "cooccurrence",
    "dedup",
    "edge_extraction",
    "embeddings",
    "extract_memory",
    "extract_memory_context",
    "extract_memory_loaders",
    "extract_memory_patterns",
    "extract_memory_processing",
    "extract_memory_streams",
    "extract_memory_text",
    "extract_memory_topics",
    "graph",
    "http_hardening",
    "integrity",
    "mcp",
    "mcp_tools",
    "merge",
    "mind_mounts",
    "mind_store",
    "minds",
    "openapi",
    "pack_mounts",
    "portability",
    "portable_builders",
    "portable_graphs",
    "portable_runtime",
    "portable_sources",
    "portable_state",
    "portable_views",
    "query",
    "query_lang",
    "search",
    "semantic_diff",
    "server",
    "service",
    "service_common",
    "service_graph_merge",
    "service_graph_queries",
    "service_objects",
    "service_runtime_agents",
    "service_runtime_common",
    "service_runtime_meta",
    "service_runtime_minds",
    "service_runtime_packs",
    "sources",
    "temporal",
    "upai",
    "webapp",
    "webapp_backend",
    "webapp_shell",
    "webapp_shell_body",
    "webapp_shell_css",
    "webapp_shell_js",
}


def __getattr__(name: str):
    export_module = _EXPORTS.get(name)
    if export_module is not None:
        value = getattr(_import_module(export_module), name)
        globals()[name] = value
        return value
    if name in _LAZY_COMPAT_SUBMODULES:
        module = _import_module(f"cortex.{name}")
        message = getattr(module, "_MESSAGE", None)
        if isinstance(message, str):
            _warnings.warn(message, DeprecationWarning, stacklevel=2)
        globals()[name] = module
        return module
    raise AttributeError(f"module 'cortex' has no attribute {name!r}")


__all__ = [
    "API_VERSION",
    "ChannelContextBridge",
    "ChannelWriteBatch",
    "ChannelMessage",
    "GenericChannelAdapter",
    "HERMES_PROFILE",
    "MemorySession",
    "OPENCLAW_PROFILE",
    "OPENAPI_VERSION",
    "__version__",
    "branch_name_for_task",
    "channel_write_plan",
    "render_search_context",
]
