from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("CORTEX_BULK_BACKEND", None)
    env.pop("CORTEX_HOT_PATH_BACKEND", None)
    env.pop("CORTEX_ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _cortex_command(*args: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        "import sys; from cortex.cli import main; raise SystemExit(main(sys.argv[1:]))",
        *args,
    ]


def test_remember_requires_global_confirmation_for_home_scoped_writes(tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = project_dir / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()

    result = subprocess.run(
        _cortex_command(
            "remember",
            "X",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ),
        cwd=project_dir,
        capture_output=True,
        check=False,
        text=True,
        env=_env(home_dir),
    )

    assert result.returncode != 0
    assert not (home_dir / ".claude" / "CLAUDE.md").exists()
    assert "The following paths are outside --project and will be written:" in result.stderr
    assert "Re-run with --global to confirm, or use --to PROJECT_TARGET to narrow." in result.stderr


def test_remember_project_target_does_not_require_global_confirmation(tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = project_dir / ".cortex"
    home_dir.mkdir()
    project_dir.mkdir()

    result = subprocess.run(
        _cortex_command(
            "remember",
            "X",
            "--to",
            "codex",
            "--project",
            str(project_dir),
            "--store-dir",
            str(store_dir),
        ),
        cwd=project_dir,
        capture_output=True,
        check=False,
        text=True,
        env=_env(home_dir),
    )

    assert result.returncode == 0, result.stderr
    assert (project_dir / "AGENTS.md").exists()
    assert not (home_dir / ".claude" / "CLAUDE.md").exists()
