from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORTEX_ROOT = REPO_ROOT / "cortex"

BANNED_EXACT_IMPORTS = {
    "cortex.adapters",
    "cortex.auth",
    "cortex.centrality",
    "cortex.claims",
    "cortex.context",
    "cortex.contradictions",
    "cortex.cooccurrence",
    "cortex.dedup",
    "cortex.edge_extraction",
    "cortex.embeddings",
    "cortex.extract_memory",
    "cortex.extract_memory_context",
    "cortex.extract_memory_loaders",
    "cortex.extract_memory_patterns",
    "cortex.extract_memory_processing",
    "cortex.extract_memory_streams",
    "cortex.extract_memory_text",
    "cortex.extract_memory_topics",
    "cortex.graph",
    "cortex.http_hardening",
    "cortex.integrity",
    "cortex.mcp",
    "cortex.mcp_tools",
    "cortex.merge",
    "cortex.mind_mounts",
    "cortex.mind_store",
    "cortex.minds",
    "cortex.openapi",
    "cortex.pack_mounts",
    "cortex.portability",
    "cortex.portable_builders",
    "cortex.portable_graphs",
    "cortex.portable_runtime",
    "cortex.portable_sources",
    "cortex.portable_state",
    "cortex.portable_views",
    "cortex.query",
    "cortex.query_lang",
    "cortex.search",
    "cortex.semantic_diff",
    "cortex.server",
    "cortex.service",
    "cortex.service_common",
    "cortex.service_graph_merge",
    "cortex.service_graph_queries",
    "cortex.service_objects",
    "cortex.service_runtime_agents",
    "cortex.service_runtime_common",
    "cortex.service_runtime_meta",
    "cortex.service_runtime_minds",
    "cortex.service_runtime_packs",
    "cortex.sources",
    "cortex.temporal",
    "cortex.webapp",
    "cortex.webapp_backend",
    "cortex.webapp_shell",
    "cortex.webapp_shell_body",
    "cortex.webapp_shell_css",
    "cortex.webapp_shell_js",
}
BANNED_IMPORT_PREFIXES = {"cortex.upai"}


def test_import_cortex_is_deprecation_warning_clean() -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", "import cortex; print(cortex.__version__)"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_internal_modules_do_not_import_deprecated_shims() -> None:
    violations: list[str] = []
    for path in sorted(CORTEX_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "deprecated; use" in text or " is deprecated; use " in text:
            continue
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if _is_deprecated_shim_import(module):
                    relative = path.relative_to(REPO_ROOT)
                    violations.append(f"{relative}:{node.lineno}: {module}")

    assert violations == []


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        modules = [node.module]
        if node.module == "cortex":
            modules.extend(f"cortex.{alias.name}" for alias in node.names)
        return modules
    return []


def _is_deprecated_shim_import(module: str) -> bool:
    if module in BANNED_EXACT_IMPORTS:
        return True
    return any(module == prefix or module.startswith(prefix + ".") for prefix in BANNED_IMPORT_PREFIXES)
