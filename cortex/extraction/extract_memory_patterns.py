from __future__ import annotations

import warnings as _warnings

import cortex.extraction.heuristic_rules as _heuristic_rules

_warnings.warn(
    "cortex.extraction.extract_memory_patterns is deprecated; use cortex.extraction.heuristic_rules instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cortex.extraction.heuristic_rules import *  # pragma: deprecation  # noqa: F401,F403,E402

__all__ = list(_heuristic_rules.__all__)

del _heuristic_rules, _warnings
