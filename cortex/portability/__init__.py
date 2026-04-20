from __future__ import annotations

import warnings as _warnings
from importlib import import_module as _import_module
from types import ModuleType as _ModuleType

_TARGET = "cortex.portability.portability"
_MESSAGE = "cortex.portability is deprecated; use cortex.portability.portability instead."
_module: _ModuleType | None = None
_public_names: list[str] | None = [
    "ADAPTERS",
    "ArtifactResult",
    "BUILTIN_POLICIES",
    "InstructionPack",
    "NormalizedContext",
    "PORTABLE_DIRECT_TARGETS",
    "PORTABLE_TARGET_ALIASES",
    "PORTABLE_TARGET_ORDER",
    "Path",
    "TYPE_CHECKING",
    "TopicDetail",
    "annotations",
    "build_instruction_pack",
    "dataclass",
    "export_artifact_targets",
    "export_chatgpt_artifacts",
    "export_claude_artifacts",
    "export_grok_artifacts",
    "json",
    "resolve_portable_targets",
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
