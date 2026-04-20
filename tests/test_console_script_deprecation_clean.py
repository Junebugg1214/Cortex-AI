from __future__ import annotations

import os
import subprocess

COMMANDS = (
    ("cortex", "--help"),
    ("cortexd", "--check"),
    ("cortex-mcp", "--check"),
    ("cortex-bench", "--help"),
    ("cortex-hook", "--help"),
)


def test_shipped_console_scripts_do_not_import_deprecated_shims() -> None:
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "error::DeprecationWarning"

    for command in COMMANDS:
        result = subprocess.run(command, capture_output=True, check=False, text=True, env=env)
        assert result.returncode == 0, f"{command!r} failed:\n{result.stderr}"
        warning_lines = [line for line in result.stderr.splitlines() if "DeprecationWarning" in line]
        assert warning_lines == []
