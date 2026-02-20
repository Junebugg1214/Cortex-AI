"""
CaaS Configuration — INI file + environment variable overrides.

Reads configuration from an INI file with sensible defaults. Environment
variables override file values using the convention CORTEX_<SECTION>_<KEY>.

Sections: server, storage, sse, webhooks, oauth, logging, security, metrics.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, dict[str, str]] = {
    "server": {
        "host": "127.0.0.1",
        "port": "8421",
        "max_body_size": "1048576",
        "allowed_origins": "",
    },
    "storage": {
        "backend": "json",
        "db_path": "cortex.db",
        "store_dir": "",
    },
    "sse": {
        "enabled": "false",
        "heartbeat_interval": "30",
        "buffer_size": "1000",
        "buffer_ttl": "3600",
    },
    "webhooks": {
        "max_retries": "3",
        "backoff_base": "5.0",
        "circuit_failure_threshold": "5",
        "circuit_cooldown": "60",
    },
    "oauth": {
        "providers": "",
        "allowed_emails": "",
    },
    "logging": {
        "level": "INFO",
        "format": "text",
    },
    "security": {
        "csrf_enabled": "true",
        "ssrf_block_private": "true",
    },
    "metrics": {
        "enabled": "false",
    },
}

_BOOL_TRUE = {"true", "yes", "1", "on"}
_BOOL_FALSE = {"false", "no", "0", "off", ""}


# ---------------------------------------------------------------------------
# CortexConfig
# ---------------------------------------------------------------------------

class CortexConfig:
    """Configuration wrapper over configparser with env var overrides."""

    def __init__(self, parser: configparser.ConfigParser) -> None:
        self._parser = parser

    # ── Factory methods ─────────────────────────────────────────────

    @classmethod
    def defaults(cls) -> CortexConfig:
        """Return a config with all default values (no file needed)."""
        parser = configparser.ConfigParser()
        for section, values in _DEFAULTS.items():
            parser[section] = dict(values)
        return cls(parser)

    @classmethod
    def from_file(cls, path: str | Path) -> CortexConfig:
        """Read an INI file, apply defaults for missing values, then apply env overrides."""
        parser = configparser.ConfigParser()
        # Seed defaults
        for section, values in _DEFAULTS.items():
            parser[section] = dict(values)

        p = Path(path)
        if p.exists():
            parser.read(str(p))
        else:
            raise FileNotFoundError(f"Config file not found: {path}")

        config = cls(parser)
        config._apply_env_overrides()
        return config

    @classmethod
    def from_env(cls) -> CortexConfig:
        """Return defaults with environment variable overrides applied."""
        config = cls.defaults()
        config._apply_env_overrides()
        return config

    # ── Access methods ──────────────────────────────────────────────

    def get(self, section: str, key: str, fallback: str = "") -> str:
        """Get a string config value."""
        # Check env override first
        env_key = f"CORTEX_{section.upper()}_{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val
        return self._parser.get(section, key, fallback=fallback)

    def getint(self, section: str, key: str, fallback: int = 0) -> int:
        """Get an integer config value."""
        raw = self.get(section, key, fallback="")
        if raw == "":
            return fallback
        try:
            return int(raw)
        except ValueError:
            raise ValueError(
                f"Invalid integer for [{section}] {key}: {raw!r}"
            )

    def getfloat(self, section: str, key: str, fallback: float = 0.0) -> float:
        """Get a float config value."""
        raw = self.get(section, key, fallback="")
        if raw == "":
            return fallback
        try:
            return float(raw)
        except ValueError:
            raise ValueError(
                f"Invalid float for [{section}] {key}: {raw!r}"
            )

    def getbool(self, section: str, key: str, fallback: bool = False) -> bool:
        """Get a boolean config value."""
        raw = self.get(section, key, fallback="")
        lower = raw.lower().strip()
        if lower in _BOOL_TRUE:
            return True
        if lower in _BOOL_FALSE:
            return fallback if lower == "" else False
        raise ValueError(
            f"Invalid boolean for [{section}] {key}: {raw!r}"
        )

    def getlist(self, section: str, key: str, fallback: list[str] | None = None) -> list[str]:
        """Get a comma-separated list config value."""
        raw = self.get(section, key, fallback="")
        if not raw.strip():
            return list(fallback) if fallback else []
        return [item.strip() for item in raw.split(",") if item.strip()]

    def sections(self) -> list[str]:
        """Return list of config sections."""
        return self._parser.sections()

    def has_section(self, section: str) -> bool:
        return self._parser.has_section(section)

    def has_option(self, section: str, key: str) -> bool:
        return self._parser.has_option(section, key)

    # ── Internal ────────────────────────────────────────────────────

    def _apply_env_overrides(self) -> None:
        """Apply CORTEX_<SECTION>_<KEY> environment variables."""
        prefix = "CORTEX_"
        for env_key, env_val in os.environ.items():
            if not env_key.startswith(prefix):
                continue
            rest = env_key[len(prefix):]
            parts = rest.split("_", 1)
            if len(parts) != 2:
                continue
            section = parts[0].lower()
            key = parts[1].lower()
            if self._parser.has_section(section):
                self._parser.set(section, key, env_val)
