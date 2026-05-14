from __future__ import annotations

import os
import re
from pathlib import Path

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def resolve_hermes_home() -> Path:
    """Resolve the Hermes state directory Cortex should target.

    Hermes uses HERMES_HOME as the source of truth. When it is unset, recent
    Hermes builds can also keep a sticky active profile in ~/.hermes/active_profile.
    """
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()

    default_home = (Path.home() / ".hermes").resolve()
    active_profile_path = default_home / "active_profile"
    try:
        active_profile = active_profile_path.read_text(encoding="utf-8").strip().lower()
    except (OSError, UnicodeDecodeError):
        active_profile = ""

    if active_profile and active_profile != "default" and _PROFILE_ID_RE.match(active_profile):
        profile_home = default_home / "profiles" / active_profile
        if profile_home.is_dir():
            return profile_home.resolve()

    return default_home


def hermes_config_path() -> Path:
    return resolve_hermes_home() / "config.yaml"


def hermes_memory_paths() -> tuple[Path, Path]:
    memories_dir = resolve_hermes_home() / "memories"
    return memories_dir / "USER.md", memories_dir / "MEMORY.md"
