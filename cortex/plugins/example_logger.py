"""
Example plugin — logs every mutation event.

Usage::

    cortex serve context.json --plugins cortex.plugins.example_logger
"""

from __future__ import annotations

import logging

logger = logging.getLogger("cortex.plugins.example_logger")

_MUTATION_HOOKS = (
    "POST_NODE_CREATE",
    "POST_NODE_UPDATE",
    "POST_NODE_DELETE",
    "POST_EDGE_CREATE",
    "POST_EDGE_DELETE",
)


def _log_event(ctx: dict) -> None:
    hook = ctx.get("hook", "unknown")
    logger.info("[plugin:logger] %s — %s", hook, ctx)


def register(registry) -> None:
    """Register logging callbacks for all mutation hooks."""
    for hook in _MUTATION_HOOKS:
        registry.on(hook, _log_event)
