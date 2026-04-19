#!/usr/bin/env python3
"""Shared runtime/connect helper surface for the Cortex CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

from cortex.atomic_io import atomic_write_text
from cortex.config import RUNTIME_MODES


def _select_scoped_api_key(
    config,
    *,
    scope: str,
    preferred_name: str = "",
    namespace: str | None = None,
):
    keys = list(config.api_keys)
    if preferred_name:
        for key in keys:
            if key.name == preferred_name:
                if not key.allows_scope(scope):
                    raise ValueError(f"API key '{preferred_name}' does not allow scope '{scope}'.")
                if namespace and not key.allows_namespace(namespace):
                    raise ValueError(f"API key '{preferred_name}' does not allow namespace '{namespace}'.")
                return key
        raise ValueError(f"API key '{preferred_name}' was not found in {config.config_path or 'the active config'}.")

    def eligible():
        for key in keys:
            if not key.allows_scope(scope):
                continue
            if namespace and not key.allows_namespace(namespace):
                continue
            yield key

    eligible_keys = list(eligible())
    preferred_order = ("reader", "read", "writer", "server-default", "env-default", "cli-default")
    for name in preferred_order:
        for key in eligible_keys:
            if key.name == name:
                return key
    return eligible_keys[0] if eligible_keys else None


def _normalize_manus_url(url: str) -> str:
    normalized = url.strip()
    if not normalized:
        return "https://your-https-endpoint.example/mcp"
    if normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    if normalized.endswith("/mcp"):
        return normalized
    return f"{normalized}/mcp"


def _build_connect_manus_serve_command(
    *,
    shell_join,
    config_path: Path | None,
    store_dir: Path,
    namespace: str | None,
    host: str,
    port: int,
) -> str:
    parts = ["cortex", "serve", "manus"]
    if config_path is not None:
        parts.extend(["--config", str(config_path)])
    else:
        parts.extend(["--store-dir", str(store_dir)])
    if namespace:
        parts.extend(["--namespace", namespace])
    parts.extend(["--host", host, "--port", str(port)])
    return shell_join(parts)


def _add_runtime_security_args(parser, *, include_legacy_manus_alias: bool = False) -> None:
    parser.add_argument(
        "--runtime-mode",
        choices=RUNTIME_MODES,
        default=None,
        help="Security posture for HTTP serving (default from config or local-single-user)",
    )
    parser.add_argument(
        "--allow-unsafe-bind",
        action="store_true",
        help="Allow a non-loopback bind even when the runtime security contract would normally refuse it.",
    )
    if include_legacy_manus_alias:
        parser.add_argument(
            "--allow-insecure-no-auth",
            dest="allow_unsafe_bind",
            action="store_true",
            help=argparse.SUPPRESS,
        )


def _connect_runtime_mcp_config_path(target: str, *, project_dir: Path) -> Path:
    from cortex.portability.context import _resolve_path

    templates = {
        "claude-code": "{project}/.mcp.json",
        "codex": "{home}/.codex/config.toml",
        "cursor": "{project}/.cursor/mcp.json",
        "hermes": "{home}/.hermes/config.yaml",
    }
    template = templates[target]
    return _resolve_path(template, str(project_dir))


def _connect_runtime_content_paths(target: str, *, project_dir: Path) -> list[str]:
    from cortex.portability.context import _resolve_path

    templates = {
        "claude-code": ("{home}/.claude/CLAUDE.md", "{project}/CLAUDE.md"),
        "codex": ("{project}/AGENTS.md",),
        "cursor": ("{project}/.cursor/rules/cortex.mdc",),
        "hermes": ("{home}/.hermes/memories/USER.md", "{home}/.hermes/memories/MEMORY.md"),
    }
    return [str(_resolve_path(template, str(project_dir))) for template in templates[target]]


def _connect_runtime_schema(target: str) -> str:
    return {
        "claude-code": "mcpServers",
        "codex": "mcp_servers",
        "cursor": "mcpServers",
        "hermes": "mcp_servers",
    }[target]


def _connect_runtime_format(target: str) -> str:
    return {
        "claude-code": "json",
        "codex": "toml",
        "cursor": "json",
        "hermes": "yaml",
    }[target]


def _connect_runtime_server_payload(cortex_config_path: Path) -> dict[str, Any]:
    return {
        "command": "cortex-mcp",
        "args": ["--config", str(cortex_config_path)],
    }


def _connect_runtime_config_snippet(target: str, *, cortex_config_path: Path) -> str:
    from cortex.hermes_integration import _render_cortex_mcp_block

    server_payload = _connect_runtime_server_payload(cortex_config_path)
    if target in {"claude-code", "cursor"}:
        return json.dumps({"mcpServers": {"cortex": server_payload}}, indent=2)
    if target == "codex":
        escaped = str(cortex_config_path).replace("\\", "\\\\").replace('"', '\\"')
        return f'[mcp_servers.cortex]\ncommand = "cortex-mcp"\nargs = ["--config", "{escaped}"]'
    if target == "hermes":
        return "\n".join(["mcp_servers:", *_render_cortex_mcp_block(cortex_config_path)])
    raise ValueError(f"Unsupported connect target: {target}")


def _connect_runtime_upsert_json_config(path: Path, *, schema: str, cortex_config_path: Path) -> dict[str, str]:
    server_payload = _connect_runtime_server_payload(cortex_config_path)
    status = "created"
    payload: dict[str, Any] = {}

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not parse existing JSON MCP config at {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"Expected a JSON object in {path}.")
        payload = loaded
        status = "updated"

    container = payload.get(schema)
    if container is None:
        container = {}
    if not isinstance(container, dict):
        raise ValueError(f"Expected `{schema}` to be a JSON object in {path}.")
    container = dict(container)
    container["cortex"] = server_payload
    payload[schema] = container

    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        status = "unchanged"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, rendered, encoding="utf-8")
    return {"path": str(path), "status": status}


def _connect_runtime_upsert_codex_config(path: Path, *, cortex_config_path: Path) -> dict[str, str]:
    escaped = str(cortex_config_path).replace("\\", "\\\\").replace('"', '\\"')
    block = [
        "[mcp_servers.cortex]",
        'command = "cortex-mcp"',
        f'args = ["--config", "{escaped}"]',
    ]
    status = "created"
    if path.exists():
        original = path.read_text(encoding="utf-8")
        try:
            tomllib.loads(original)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Could not parse existing Codex config at {path}: {exc}") from exc
        lines = original.splitlines()
        start = None
        for index, line in enumerate(lines):
            if line.strip() == "[mcp_servers.cortex]":
                start = index
                break
        if start is not None:
            end = len(lines)
            for index in range(start + 1, len(lines)):
                stripped = lines[index].strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    end = index
                    break
            updated_lines = lines[:start] + block + lines[end:]
        else:
            updated_lines = list(lines)
            if updated_lines and updated_lines[-1].strip():
                updated_lines.append("")
            updated_lines.extend(block)
        rendered = "\n".join(updated_lines).rstrip() + "\n"
        status = "updated"
        if rendered == original:
            status = "unchanged"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, rendered, encoding="utf-8")
        return {"path": str(path), "status": status}

    rendered = "\n".join(block) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, rendered, encoding="utf-8")
    return {"path": str(path), "status": status}


def _connect_runtime_upsert_target_config(target: str, *, path: Path, cortex_config_path: Path) -> dict[str, str]:
    from cortex.hermes_integration import update_hermes_config

    if target in {"claude-code", "cursor"}:
        return _connect_runtime_upsert_json_config(
            path,
            schema=_connect_runtime_schema(target),
            cortex_config_path=cortex_config_path,
        )
    if target == "codex":
        return _connect_runtime_upsert_codex_config(path, cortex_config_path=cortex_config_path)
    if target == "hermes":
        status = update_hermes_config(path, cortex_config_path=cortex_config_path, dry_run=False)
        return {"path": str(path), "status": status}
    raise ValueError(f"Unsupported connect target: {target}")


def _connect_runtime_context_status(store_dir: Path) -> dict[str, Any]:
    from cortex.graph.minds import load_mind_core_graph, resolve_default_mind
    from cortex.portability.portable_runtime import load_canonical_graph, load_portability_state

    try:
        default_mind = resolve_default_mind(store_dir)
    except (FileNotFoundError, ValueError):
        default_mind = None

    if default_mind:
        payload = load_mind_core_graph(store_dir, default_mind)
        return {
            "default_mind": default_mind,
            "context_ready": payload["fact_count"] > 0,
            "fact_count": payload["fact_count"],
            "graph_ref": payload["graph_ref"],
            "graph_source": payload["graph_source"],
        }

    state = load_portability_state(store_dir)
    graph, graph_path = load_canonical_graph(store_dir, state)
    return {
        "default_mind": "",
        "context_ready": len(graph.nodes) > 0,
        "fact_count": len(graph.nodes),
        "graph_ref": str(graph_path),
        "graph_source": "portable_canonical_graph" if graph.nodes else "empty_graph",
    }


def _connect_runtime_next_steps(
    *,
    target: str,
    project_dir: Path,
    mcp_configured: bool,
    context_status: dict[str, Any],
) -> list[str]:
    steps: list[str] = []
    if not mcp_configured:
        steps.append(f"Run `cortex connect {target} --install --project {project_dir}` to wire the local MCP config.")
    default_mind = str(context_status.get("default_mind") or "")
    if default_mind:
        steps.append(f"Run `cortex mind mount {default_mind} --to {target} --project {project_dir} --smart`.")
    elif context_status.get("context_ready"):
        steps.append(f"Run `cortex sync --smart --to {target} --project {project_dir}`.")
    else:
        steps.append('Run `cortex init` or `cortex mind remember <mind> "..."` before mounting context into this tool.')
    return steps


def _serve_check_payload(
    *, target: str, mode: str, config, selection, allow_unsafe_bind: bool = False
) -> dict[str, Any]:
    from cortex.config import startup_diagnostics

    diagnostics = startup_diagnostics(config, mode=mode)
    warnings = [*selection.warnings, *diagnostics["warnings"]]
    return {
        "status": "ok",
        "target": target,
        "store_source": selection.source,
        "allow_unsafe_bind": bool(allow_unsafe_bind),
        **{**diagnostics, "warnings": warnings},
    }


__all__ = [
    "_add_runtime_security_args",
    "_build_connect_manus_serve_command",
    "_connect_runtime_config_snippet",
    "_connect_runtime_content_paths",
    "_connect_runtime_context_status",
    "_connect_runtime_format",
    "_connect_runtime_mcp_config_path",
    "_connect_runtime_next_steps",
    "_connect_runtime_schema",
    "_connect_runtime_server_payload",
    "_connect_runtime_upsert_codex_config",
    "_connect_runtime_upsert_json_config",
    "_connect_runtime_upsert_target_config",
    "_normalize_manus_url",
    "_select_scoped_api_key",
    "_serve_check_payload",
]
