"""Tests for cortex.caas.config — Configuration system."""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path

import pytest

from cortex.caas.config import CortexConfig, _DEFAULTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_ini(tmp_path: Path, content: str) -> Path:
    ini_path = tmp_path / "cortex.ini"
    ini_path.write_text(textwrap.dedent(content))
    return ini_path


# ---------------------------------------------------------------------------
# TestDefaults
# ---------------------------------------------------------------------------

class TestDefaults:
    """CortexConfig.defaults() returns sensible values for all keys."""

    def test_default_host(self):
        cfg = CortexConfig.defaults()
        assert cfg.get("server", "host") == "127.0.0.1"

    def test_default_port(self):
        cfg = CortexConfig.defaults()
        assert cfg.getint("server", "port") == 8421

    def test_default_max_body_size(self):
        cfg = CortexConfig.defaults()
        assert cfg.getint("server", "max_body_size") == 1_048_576

    def test_default_storage_backend(self):
        cfg = CortexConfig.defaults()
        assert cfg.get("storage", "backend") == "json"

    def test_default_sse_enabled(self):
        cfg = CortexConfig.defaults()
        assert cfg.getbool("sse", "enabled") is False

    def test_default_heartbeat(self):
        cfg = CortexConfig.defaults()
        assert cfg.getint("sse", "heartbeat_interval") == 30

    def test_default_webhooks_max_retries(self):
        cfg = CortexConfig.defaults()
        assert cfg.getint("webhooks", "max_retries") == 3

    def test_default_backoff_base(self):
        cfg = CortexConfig.defaults()
        assert cfg.getfloat("webhooks", "backoff_base") == 5.0

    def test_default_log_level(self):
        cfg = CortexConfig.defaults()
        assert cfg.get("logging", "level") == "INFO"

    def test_default_log_format(self):
        cfg = CortexConfig.defaults()
        assert cfg.get("logging", "format") == "text"

    def test_default_csrf_enabled(self):
        cfg = CortexConfig.defaults()
        assert cfg.getbool("security", "csrf_enabled") is True

    def test_default_ssrf_block(self):
        cfg = CortexConfig.defaults()
        assert cfg.getbool("security", "ssrf_block_private") is True

    def test_default_circuit_threshold(self):
        cfg = CortexConfig.defaults()
        assert cfg.getint("webhooks", "circuit_failure_threshold") == 5

    def test_default_circuit_cooldown(self):
        cfg = CortexConfig.defaults()
        assert cfg.getfloat("webhooks", "circuit_cooldown") == 60.0

    def test_all_default_sections_present(self):
        cfg = CortexConfig.defaults()
        for section in _DEFAULTS:
            assert cfg.has_section(section), f"Missing section: {section}"

    def test_default_db_path(self):
        cfg = CortexConfig.defaults()
        assert cfg.get("storage", "db_path") == "cortex.db"


# ---------------------------------------------------------------------------
# TestFileLoading
# ---------------------------------------------------------------------------

class TestFileLoading:
    """CortexConfig.from_file() reads INI files correctly."""

    def test_reads_custom_port(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [server]
        port = 9000
        """)
        cfg = CortexConfig.from_file(ini)
        assert cfg.getint("server", "port") == 9000

    def test_preserves_defaults_for_missing_keys(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [server]
        port = 9000
        """)
        cfg = CortexConfig.from_file(ini)
        assert cfg.get("server", "host") == "127.0.0.1"

    def test_reads_storage_section(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [storage]
        backend = sqlite
        db_path = /data/cortex.db
        """)
        cfg = CortexConfig.from_file(ini)
        assert cfg.get("storage", "backend") == "sqlite"
        assert cfg.get("storage", "db_path") == "/data/cortex.db"

    def test_reads_sse_section(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [sse]
        enabled = true
        buffer_size = 5000
        """)
        cfg = CortexConfig.from_file(ini)
        assert cfg.getbool("sse", "enabled") is True
        assert cfg.getint("sse", "buffer_size") == 5000

    def test_reads_logging_section(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [logging]
        level = DEBUG
        format = json
        """)
        cfg = CortexConfig.from_file(ini)
        assert cfg.get("logging", "level") == "DEBUG"
        assert cfg.get("logging", "format") == "json"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CortexConfig.from_file(tmp_path / "nonexistent.ini")

    def test_multiple_sections(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [server]
        port = 7000

        [security]
        csrf_enabled = false
        """)
        cfg = CortexConfig.from_file(ini)
        assert cfg.getint("server", "port") == 7000
        assert cfg.getbool("security", "csrf_enabled") is False

    def test_empty_file_returns_defaults(self, tmp_path):
        ini = _write_ini(tmp_path, "")
        cfg = CortexConfig.from_file(ini)
        assert cfg.getint("server", "port") == 8421


# ---------------------------------------------------------------------------
# TestEnvOverrides
# ---------------------------------------------------------------------------

class TestEnvOverrides:
    """Environment variables override file and default values."""

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("CORTEX_SERVER_PORT", "9999")
        cfg = CortexConfig.from_env()
        assert cfg.getint("server", "port") == 9999

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        ini = _write_ini(tmp_path, """
        [server]
        port = 7000
        """)
        monkeypatch.setenv("CORTEX_SERVER_PORT", "8888")
        cfg = CortexConfig.from_file(ini)
        assert cfg.getint("server", "port") == 8888

    def test_env_override_boolean(self, monkeypatch):
        monkeypatch.setenv("CORTEX_SSE_ENABLED", "true")
        cfg = CortexConfig.from_env()
        assert cfg.getbool("sse", "enabled") is True

    def test_env_override_float(self, monkeypatch):
        monkeypatch.setenv("CORTEX_WEBHOOKS_BACKOFF_BASE", "10.5")
        cfg = CortexConfig.from_env()
        assert cfg.getfloat("webhooks", "backoff_base") == 10.5

    def test_env_unknown_section_ignored(self, monkeypatch):
        monkeypatch.setenv("CORTEX_UNKNOWN_KEY", "value")
        cfg = CortexConfig.from_env()
        # Should not crash, just silently ignore
        assert cfg.get("server", "host") == "127.0.0.1"

    def test_env_prefix_case_insensitive_section(self, monkeypatch):
        monkeypatch.setenv("CORTEX_LOGGING_LEVEL", "DEBUG")
        cfg = CortexConfig.from_env()
        assert cfg.get("logging", "level") == "DEBUG"


# ---------------------------------------------------------------------------
# TestTypeCoercion
# ---------------------------------------------------------------------------

class TestTypeCoercion:
    """Type conversion methods work correctly."""

    def test_getint_valid(self):
        cfg = CortexConfig.defaults()
        assert cfg.getint("server", "port") == 8421

    def test_getint_fallback(self):
        cfg = CortexConfig.defaults()
        assert cfg.getint("server", "nonexistent", fallback=42) == 42

    def test_getint_invalid_raises(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [server]
        port = not_a_number
        """)
        cfg = CortexConfig.from_file(ini)
        with pytest.raises(ValueError, match="Invalid integer"):
            cfg.getint("server", "port")

    def test_getfloat_valid(self):
        cfg = CortexConfig.defaults()
        assert cfg.getfloat("webhooks", "backoff_base") == 5.0

    def test_getfloat_fallback(self):
        cfg = CortexConfig.defaults()
        assert cfg.getfloat("server", "nonexistent", fallback=3.14) == 3.14

    def test_getfloat_invalid_raises(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [webhooks]
        backoff_base = xyz
        """)
        cfg = CortexConfig.from_file(ini)
        with pytest.raises(ValueError, match="Invalid float"):
            cfg.getfloat("webhooks", "backoff_base")

    def test_getbool_true_values(self, tmp_path):
        for val in ["true", "True", "TRUE", "yes", "1", "on"]:
            ini = _write_ini(tmp_path, f"""
            [sse]
            enabled = {val}
            """)
            cfg = CortexConfig.from_file(ini)
            assert cfg.getbool("sse", "enabled") is True, f"Failed for {val!r}"

    def test_getbool_false_values(self, tmp_path):
        for val in ["false", "False", "FALSE", "no", "0", "off"]:
            ini = _write_ini(tmp_path, f"""
            [sse]
            enabled = {val}
            """)
            cfg = CortexConfig.from_file(ini)
            assert cfg.getbool("sse", "enabled") is False, f"Failed for {val!r}"

    def test_getbool_invalid_raises(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [sse]
        enabled = maybe
        """)
        cfg = CortexConfig.from_file(ini)
        with pytest.raises(ValueError, match="Invalid boolean"):
            cfg.getbool("sse", "enabled")

    def test_getbool_fallback(self):
        cfg = CortexConfig.defaults()
        assert cfg.getbool("server", "nonexistent", fallback=True) is True

    def test_getlist_empty(self):
        cfg = CortexConfig.defaults()
        assert cfg.getlist("server", "allowed_origins") == []

    def test_getlist_populated(self, tmp_path):
        ini = _write_ini(tmp_path, """
        [server]
        allowed_origins = http://a.com, http://b.com
        """)
        cfg = CortexConfig.from_file(ini)
        result = cfg.getlist("server", "allowed_origins")
        assert result == ["http://a.com", "http://b.com"]

    def test_getlist_fallback(self):
        cfg = CortexConfig.defaults()
        result = cfg.getlist("server", "nonexistent", fallback=["x"])
        assert result == ["x"]


# ---------------------------------------------------------------------------
# TestAccessPatterns
# ---------------------------------------------------------------------------

class TestAccessPatterns:
    """Various access patterns work correctly."""

    def test_get_missing_key_returns_fallback(self):
        cfg = CortexConfig.defaults()
        assert cfg.get("server", "nonexistent", fallback="default") == "default"

    def test_has_section(self):
        cfg = CortexConfig.defaults()
        assert cfg.has_section("server")
        assert not cfg.has_section("nonexistent")

    def test_has_option(self):
        cfg = CortexConfig.defaults()
        assert cfg.has_option("server", "port")
        assert not cfg.has_option("server", "nonexistent")

    def test_sections_list(self):
        cfg = CortexConfig.defaults()
        sections = cfg.sections()
        assert "server" in sections
        assert "storage" in sections
        assert "logging" in sections
