"""
Example plugin — validates node labels are non-empty before creation.

Usage::

    cortex serve context.json --plugins cortex.plugins.example_validator
"""

from __future__ import annotations

import logging

logger = logging.getLogger("cortex.plugins.example_validator")


def _validate_node_label(ctx: dict) -> None:
    """Log a warning if a node label looks suspicious."""
    label = ctx.get("label", "")
    if label and len(label) > 200:
        logger.warning(
            "[plugin:validator] Node label exceeds 200 chars: %s...",
            label[:50],
        )


def register(registry) -> None:
    """Register validation callbacks."""
    registry.on("PRE_NODE_CREATE", _validate_node_label)
