from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPORT_BUDGET_MS = 120
HELP_BUDGET_MS = 200
STATUS_BUDGET_MS = 220


def _budget_ms(base_ms: int) -> float:
    multiplier = float(os.environ.get("CORTEX_STARTUP_CI_MULTIPLIER", "1"))
    return base_ms * multiplier


def _env() -> dict[str, str]:
    return {
        "CORTEX_STARTUP_CI_MULTIPLIER": os.environ.get("CORTEX_STARTUP_CI_MULTIPLIER", "1"),
        "PYTHONWARNINGS": "ignore::DeprecationWarning",
        "PATH": "/usr/bin:/bin",
    }


def _time_cmd(args: list[str], budget_ms: int, *, cwd: Path = REPO_ROOT) -> float:
    t0 = time.perf_counter()
    result = subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        capture_output=True,
        check=False,
        env=_env(),
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert result.returncode == 0, result.stderr.decode()[:500]
    effective_budget = _budget_ms(budget_ms)
    assert elapsed_ms <= effective_budget, f"expected <= {effective_budget:.0f}ms, got {elapsed_ms:.0f}ms"
    return elapsed_ms


def test_import_cortex_cold_is_under_budget() -> None:
    _time_cmd(["-c", "import cortex"], IMPORT_BUDGET_MS)


def test_cortex_help_cold_is_under_budget() -> None:
    _time_cmd(["-m", "cortex", "--help"], HELP_BUDGET_MS)


def test_cortex_status_cold_is_under_budget(tmp_path: Path) -> None:
    store_dir = tmp_path / ".cortex"
    init_result = subprocess.run(
        [sys.executable, "-m", "cortex", "init", "--store-dir", str(store_dir)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        env=_env(),
    )
    assert init_result.returncode == 0, init_result.stderr.decode()[:500]
    _time_cmd(["-m", "cortex", "status", "--store-dir", str(store_dir)], STATUS_BUDGET_MS, cwd=tmp_path)


def _importtime_log(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    result = subprocess.run(
        [sys.executable, "-X", "importtime", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
        env=_env(),
    )
    assert result.returncode == 0, result.stderr.decode()[:500]
    return result.stderr.decode()


def test_no_extraction_imports_on_cortex_help(tmp_path: Path) -> None:
    """Proof that trivial CLI calls do not pull in heavyweight runtimes."""
    store_dir = tmp_path / ".cortex"
    init_result = subprocess.run(
        [sys.executable, "-m", "cortex", "init", "--store-dir", str(store_dir)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        env=_env(),
    )
    assert init_result.returncode == 0, init_result.stderr.decode()[:500]

    forbidden = [
        "cortex.extraction.model_backend",
        "cortex.extraction.hybrid_backend",
        "cortex.extraction.embedding_backend",
        "cortex.extraction.llm_provider",
        "cortex.mcp.mcp_tools",
        "cortex.service.openapi",
        "cortex.service.asgi_app",
        "anthropic",
        "sentence_transformers",
    ]
    traces = {
        "cortex --help": _importtime_log(["-m", "cortex", "--help"]),
        "cortex status": _importtime_log(
            ["-m", "cortex", "status", "--store-dir", str(store_dir)],
            cwd=tmp_path,
        ),
    }
    offenders = {
        name: [mod for mod in forbidden if mod in log]
        for name, log in traces.items()
        if any(mod in log for mod in forbidden)
    }
    assert not offenders, f"trivial CLI calls pulled in: {offenders}"
