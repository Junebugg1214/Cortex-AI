"""
Cortex Plugin System — hook-based extensibility for the CaaS server.

Plugins are Python modules that export a ``register(registry)`` function.
The registry provides ``on(hook_name, callback)`` for subscribing to lifecycle
events.  Errors in plugin callbacks are caught and logged — they never crash
the server.

Hooks
-----
PRE_NODE_CREATE   — fired before a node is persisted
POST_NODE_CREATE  — fired after a node is persisted
PRE_NODE_UPDATE   — fired before a node is updated
POST_NODE_UPDATE  — fired after a node is updated
PRE_NODE_DELETE   — fired before a node is deleted
POST_NODE_DELETE  — fired after a node is deleted
PRE_EDGE_CREATE   — fired before an edge is persisted
POST_EDGE_CREATE  — fired after an edge is persisted
PRE_EDGE_DELETE   — fired before an edge is deleted
POST_EDGE_DELETE  — fired after an edge is deleted
PRE_SEARCH        — fired before a search is executed
POST_SEARCH       — fired after search results are computed

Usage::

    # my_plugin.py
    def register(registry):
        registry.on("POST_NODE_CREATE", lambda ctx: print(ctx["node_id"]))
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Callable

logger = logging.getLogger("cortex.plugins")

# ---------------------------------------------------------------------------
# Hook names — canonical set
# ---------------------------------------------------------------------------

HOOKS: frozenset[str] = frozenset({
    "PRE_NODE_CREATE",
    "POST_NODE_CREATE",
    "PRE_NODE_UPDATE",
    "POST_NODE_UPDATE",
    "PRE_NODE_DELETE",
    "POST_NODE_DELETE",
    "PRE_EDGE_CREATE",
    "POST_EDGE_CREATE",
    "PRE_EDGE_DELETE",
    "POST_EDGE_DELETE",
    "PRE_SEARCH",
    "POST_SEARCH",
})

HookCallback = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# PluginRegistry
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Manages hook subscriptions for plugins."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookCallback]] = {h: [] for h in HOOKS}
        self._plugin_names: list[str] = []

    def on(self, hook: str, callback: HookCallback) -> None:
        """Subscribe *callback* to *hook*.

        Raises ``ValueError`` if *hook* is not a recognised hook name.
        """
        if hook not in HOOKS:
            raise ValueError(
                f"Unknown hook {hook!r}. Valid hooks: {sorted(HOOKS)}"
            )
        self._hooks[hook].append(callback)

    @property
    def hook_names(self) -> frozenset[str]:
        return HOOKS

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._plugin_names)

    def subscriber_count(self, hook: str) -> int:
        """Return the number of callbacks registered for *hook*."""
        return len(self._hooks.get(hook, []))


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------

class PluginManager:
    """Load plugins and fire hooks at runtime.

    Parameters
    ----------
    modules : list[str]
        Dotted Python module names to import.  Each must expose a
        ``register(registry)`` callable.
    """

    def __init__(self, modules: list[str] | None = None) -> None:
        self._registry = PluginRegistry()
        if modules:
            for mod_name in modules:
                self.load(mod_name)

    # ── loading ──────────────────────────────────────────────────────

    def load(self, module_name: str) -> None:
        """Import *module_name* and call its ``register(registry)``."""
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            logger.exception("Failed to import plugin %s", module_name)
            return

        register_fn = getattr(mod, "register", None)
        if not callable(register_fn):
            logger.warning(
                "Plugin %s has no callable 'register' — skipped", module_name
            )
            return

        try:
            register_fn(self._registry)
            self._registry._plugin_names.append(module_name)
            logger.info("Loaded plugin: %s", module_name)
        except Exception:
            logger.exception("Error in register() for plugin %s", module_name)

    # ── firing hooks ─────────────────────────────────────────────────

    def fire(self, hook: str, context: dict[str, Any] | None = None) -> None:
        """Fire *hook* with optional *context* dict.

        Each callback is called in registration order.  Errors are logged
        but never propagated.
        """
        if hook not in HOOKS:
            return
        ctx = context or {}
        for cb in self._registry._hooks[hook]:
            try:
                cb(ctx)
            except Exception:
                logger.exception(
                    "Error in plugin callback for hook %s", hook
                )

    # ── introspection ────────────────────────────────────────────────

    @property
    def registry(self) -> PluginRegistry:
        return self._registry

    @property
    def loaded_plugins(self) -> list[str]:
        return self._registry.loaded_plugins

    def subscriber_count(self, hook: str) -> int:
        return self._registry.subscriber_count(hook)
