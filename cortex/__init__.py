"""Cortex — local AI identity and memory toolkit."""

from importlib import import_module as _import_module

from cortex.channel_runtime import (
    HERMES_PROFILE,
    OPENCLAW_PROFILE,
    ChannelContextBridge,
    ChannelMessage,
    ChannelWriteBatch,
    GenericChannelAdapter,
    channel_write_plan,
)
from cortex.release import API_VERSION, OPENAPI_VERSION, PROJECT_VERSION
from cortex.session import MemorySession, branch_name_for_task, render_search_context

__version__ = PROJECT_VERSION

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
    "service_runtime",
    "service_runtime_agents",
    "service_runtime_channels",
    "service_runtime_common",
    "service_runtime_meta",
    "service_runtime_minds",
    "service_runtime_packs",
    "service_runtime_portability",
    "service_versioned_graph",
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
    if name in _LAZY_COMPAT_SUBMODULES:
        module = _import_module(f"cortex.{name}")
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
