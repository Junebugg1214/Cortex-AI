#!/usr/bin/env python3
"""Runtime command handlers for the Cortex CLI."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cortex.cli_runtime import (
    _connect_runtime_config_snippet,
    _connect_runtime_content_paths,
    _connect_runtime_context_status,
    _connect_runtime_format,
    _connect_runtime_mcp_config_path,
    _connect_runtime_next_steps,
    _connect_runtime_upsert_target_config,
    _serve_check_payload,
)
from cortex.runtime_control import ShutdownController, install_shutdown_handlers
from cortex.runtime_logging import configure_structured_logging, get_logger, log_operation

LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class RuntimeCliContext:
    """Callbacks supplied by the main CLI module."""

    emit_result: Callable[[Any, str], int]
    echo: Callable[..., None]
    error: Callable[..., int]
    emit_compatibility_note: Callable[..., None]
    load_first_class_runtime_config: Callable[..., Any]
    runtime_forward_argv: Callable[..., list[str]]
    shell_join: Callable[[list[str]], str]


def _load_runtime_check_config(
    ctx: RuntimeCliContext,
    *,
    command: str,
    store_dir: str | None,
    context_file: str | None,
    config_path: str | None,
    host: str | None = None,
    port: int | None = None,
    runtime_mode: str | None = None,
    namespace: str | None = None,
    api_key: str | None = None,
):
    return ctx.load_first_class_runtime_config(
        command=command,
        store_dir=store_dir,
        context_file=context_file,
        config_path=config_path,
        host=host,
        port=port,
        runtime_mode=runtime_mode,
        namespace=namespace,
        api_key=api_key,
    )


def run_connect_runtime_target(args, *, target: str, ctx: RuntimeCliContext) -> int:
    from cortex.hermes_integration import ensure_cortex_mcp_config
    from cortex.portability.portable_runtime import display_name, scan_portability

    project_dir = Path(args.project) if getattr(args, "project", None) else Path.cwd()
    warnings: list[str] = []
    errors: list[str] = []

    try:
        runtime_config, selection = ctx.load_first_class_runtime_config(
            command=f"connect {target}",
            store_dir=args.store_dir,
            config_path=args.config,
        )
    except ValueError as exc:
        return ctx.error(str(exc))

    warnings.extend(selection.warnings)
    store_dir = runtime_config.store_dir.resolve()
    explicit_config_path = Path(args.config).expanduser().resolve() if getattr(args, "config", None) else None
    if explicit_config_path is not None and not explicit_config_path.exists():
        errors.append(f"Config path not found: {explicit_config_path}")

    shared_config_path = (
        explicit_config_path
        if explicit_config_path is not None
        else (
            runtime_config.config_path.resolve()
            if runtime_config.config_path
            else (store_dir / "config.toml").resolve()
        )
    )
    shared_config_exists = shared_config_path.exists()
    config_created = False
    install_actions: list[dict[str, str]] = []

    if not shared_config_exists and not explicit_config_path:
        warnings.append(
            f"No Cortex config.toml was found yet; `--install` will create one at {shared_config_path} for cortex-mcp."
        )

    if args.install and not errors:
        if not shared_config_exists:
            if explicit_config_path is not None:
                errors.append(f"Cannot install using a missing explicit config path: {explicit_config_path}")
            else:
                shared_config_path = ensure_cortex_mcp_config(store_dir, dry_run=False).resolve()
                config_created = True
                shared_config_exists = True
                install_actions.append(
                    {
                        "action": "create_cortex_config",
                        "path": str(shared_config_path),
                        "status": "created",
                    }
                )
        if shared_config_exists:
            try:
                target_result = _connect_runtime_upsert_target_config(
                    target,
                    path=_connect_runtime_mcp_config_path(target, project_dir=project_dir),
                    cortex_config_path=shared_config_path,
                )
            except ValueError as exc:
                errors.append(str(exc))
            else:
                install_actions.append(
                    {
                        "action": "write_target_mcp_config",
                        "path": target_result["path"],
                        "status": target_result["status"],
                    }
                )

    try:
        scan_payload = scan_portability(store_dir=store_dir, project_dir=project_dir)
    except ValueError as exc:
        return ctx.error(str(exc))
    tool = {item["target"]: item for item in scan_payload["tools"]}[target]
    context_status = _connect_runtime_context_status(store_dir)
    target_mcp_config_path = _connect_runtime_mcp_config_path(target, project_dir=project_dir)

    if not tool["cortex_mcp_configured"]:
        warnings.append(f"{display_name(target)} is not configured to run `cortex-mcp` yet.")
    if not context_status["context_ready"]:
        warnings.append("No portable context is ready yet; wire the runtime first, then mount or sync a Mind into it.")

    status = "error" if errors else ("ok" if tool["cortex_mcp_configured"] else "warn")
    payload = {
        "status": status,
        "target": target,
        "display_name": display_name(target),
        "store_dir": str(store_dir),
        "store_source": selection.source,
        "config_path": str(shared_config_path) if shared_config_exists else None,
        "project_dir": str(project_dir.resolve()),
        "mcp_command": ctx.shell_join(["cortex-mcp", "--config", str(shared_config_path)]),
        "mcp_config_path": str(target_mcp_config_path),
        "config_format": _connect_runtime_format(target),
        "mcp_configured": bool(tool["cortex_mcp_configured"]),
        "mcp_server_count": int(tool["mcp_server_count"]),
        "mcp_paths": list(tool["mcp_paths"]),
        "content_paths": list(tool["detected_paths"]),
        "managed_content_paths": _connect_runtime_content_paths(target, project_dir=project_dir),
        "configured": bool(tool["configured"]),
        "context_ready": bool(context_status["context_ready"]),
        "default_mind": str(context_status["default_mind"]),
        "graph_ref": str(context_status["graph_ref"]),
        "graph_source": str(context_status["graph_source"]),
        "fact_count": int(context_status["fact_count"]),
        "config_created": config_created,
        "warnings": warnings,
        "errors": errors,
        "next_steps": _connect_runtime_next_steps(
            target=target,
            project_dir=project_dir.resolve(),
            mcp_configured=bool(tool["cortex_mcp_configured"]),
            context_status=context_status,
        ),
    }
    if args.print_config:
        payload["config_snippet"] = _connect_runtime_config_snippet(target, cortex_config_path=shared_config_path)
    if args.install:
        payload["install_actions"] = install_actions

    if ctx.emit_result(payload, args.format) == 0:
        return 1 if errors or (args.check and not tool["cortex_mcp_configured"]) else 0

    ctx.echo(f"Cortex ↔ {payload['display_name']}")
    ctx.echo(f"  Status:      {payload['status']}")
    ctx.echo(f"  Store:       {payload['store_dir']}")
    ctx.echo(f"  Store src:   {payload['store_source']}")
    ctx.echo(f"  MCP config:  {payload['mcp_config_path']}")
    if payload["config_path"]:
        ctx.echo(f"  Cortex cfg:  {payload['config_path']}")
    ctx.echo(f"  MCP ready:   {'yes' if payload['mcp_configured'] else 'no'}")
    ctx.echo(f"  Context:     {payload['fact_count']} facts from {payload['graph_source']}")
    if payload["mcp_paths"]:
        ctx.echo("  Detected MCP paths:")
        for path in payload["mcp_paths"]:
            ctx.echo(f"    - {path}")
    if payload["content_paths"]:
        ctx.echo("  Detected context files:")
        for path in payload["content_paths"]:
            ctx.echo(f"    - {path}")
    for action in install_actions:
        ctx.echo(f"  Install:     {action['action']} ({action['status']}) -> {action['path']}")
    for message in warnings:
        ctx.echo(f"  Warning:     {message}")
    for message in errors:
        ctx.echo(f"  Error:       {message}")
    if args.print_config:
        ctx.echo("")
        ctx.echo("Config snippet:")
        ctx.echo(payload["config_snippet"])
    ctx.echo("")
    ctx.echo("Next:")
    for step in payload["next_steps"]:
        ctx.echo(f"  {step}")
    return 1 if errors or (args.check and not tool["cortex_mcp_configured"]) else 0


def run_ui(args, *, ctx: RuntimeCliContext) -> int:
    """Launch the local Cortex infrastructure UI."""
    from cortex.config import format_startup_diagnostics, validate_runtime_security
    from cortex.service.webapp import start_ui_server

    configure_structured_logging()
    if getattr(args, "subcommand", "") == "ui":
        ctx.emit_compatibility_note("ui", "cortex serve ui")

    try:
        config, selection = _load_runtime_check_config(
            ctx,
            command="serve ui",
            store_dir=args.store_dir,
            context_file=args.context_file,
            config_path=getattr(args, "config", None),
            host=args.host or "127.0.0.1",
            port=args.port if args.port is not None else 8765,
            runtime_mode=args.runtime_mode,
        )
    except ValueError as exc:
        return ctx.error(str(exc))

    try:
        validate_runtime_security(
            surface="ui",
            host=config.server_host,
            runtime_mode=config.runtime_mode,
            allow_unsafe_bind=args.allow_unsafe_bind,
        )
    except ValueError as exc:
        return ctx.error(str(exc))

    if args.check and getattr(args, "format", "text") == "json":
        payload = _serve_check_payload(
            target="ui",
            mode="ui",
            config=config,
            selection=selection,
            allow_unsafe_bind=args.allow_unsafe_bind,
        )
        ctx.emit_result(payload, "json")
        return 0
    if args.check:
        ctx.echo(format_startup_diagnostics(config, mode="ui"), force=True)
        for warning in selection.warnings:
            ctx.echo(f"  Warning: {warning}", force=True)
        return 0
    for warning in selection.warnings:
        ctx.echo(f"Warning: {warning}", stderr=True)

    server, url = start_ui_server(
        host=config.server_host,
        port=config.server_port,
        store_dir=str(config.store_dir),
        context_file=config.context_file,
        open_browser=args.open,
        runtime_mode=config.runtime_mode,
        allow_unsafe_bind=args.allow_unsafe_bind,
        api_keys=config.api_keys,
    )
    controller = ShutdownController()
    log_operation(
        LOGGER,
        logging.INFO,
        "startup",
        "Cortex UI diagnostics:",
        diagnostics=format_startup_diagnostics(config, mode="ui"),
    )
    log_operation(LOGGER, logging.INFO, "startup", f"Cortex UI running at {url}", url=url)
    with install_shutdown_handlers(controller):
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
        thread.start()
        try:
            while thread.is_alive() and not controller.wait(0.5):
                continue
        except KeyboardInterrupt:
            controller.request_shutdown("Received KeyboardInterrupt")
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
    log_operation(
        LOGGER,
        logging.INFO,
        "shutdown",
        "Cortex UI stopped.",
        reason=controller.reason or "Process exit",
    )
    return 0


def run_server(args, *, ctx: RuntimeCliContext) -> int:
    """Launch the local Cortex REST API server."""
    from cortex.config import validate_runtime_security
    from cortex.service.server import main as server_main

    if getattr(args, "subcommand", "") == "server":
        ctx.emit_compatibility_note("server", "cortex serve api", format_name=getattr(args, "format", None))

    if args.check and args.format == "json":
        try:
            config, selection = _load_runtime_check_config(
                ctx,
                command="serve api",
                store_dir=args.store_dir,
                context_file=args.context_file,
                config_path=args.config,
                host=args.host,
                port=args.port,
                runtime_mode=args.runtime_mode,
                api_key=args.api_key,
            )
            validate_runtime_security(
                surface="api",
                host=config.server_host,
                runtime_mode=config.runtime_mode,
                api_keys=config.api_keys,
                allow_unsafe_bind=args.allow_unsafe_bind,
            )
            payload = _serve_check_payload(
                target="api",
                mode="server",
                config=config,
                selection=selection,
                allow_unsafe_bind=args.allow_unsafe_bind,
            )
        except ValueError as exc:
            return ctx.error(str(exc))
        ctx.emit_result(payload, "json")
        return 0

    try:
        config, selection = _load_runtime_check_config(
            ctx,
            command="serve api",
            store_dir=args.store_dir,
            context_file=args.context_file,
            config_path=args.config,
            host=args.host,
            port=args.port,
            runtime_mode=args.runtime_mode,
            api_key=args.api_key,
        )
    except ValueError as exc:
        return ctx.error(str(exc))
    for warning in selection.warnings:
        ctx.echo(f"Warning: {warning}", stderr=True)
    if getattr(args, "asgi", False):
        try:
            from cortex.service.asgi_app import run_asgi_server
        except ImportError:
            return ctx.error(
                "ASGI serving requires optional dependencies.",
                hint="Install `cortex-identity[asgi]`, then rerun `cortex serve api --asgi`.",
            )
        return run_asgi_server(
            host=config.server_host,
            port=config.server_port,
            store_dir=config.store_dir,
            context_file=config.context_file,
            runtime_mode=config.runtime_mode,
            auth_keys=config.api_keys,
            allow_unsafe_bind=args.allow_unsafe_bind,
            external_base_url=config.external_base_url,
            rate_limit_backend=config.ratelimit_backend,
            cors_origins=tuple(getattr(args, "cors_origin", ()) or ()),
        )
    argv = ctx.runtime_forward_argv(
        selection=selection,
        explicit_config_path=args.config,
        context_file=args.context_file,
        host=args.host,
        port=args.port,
        runtime_mode=args.runtime_mode,
        api_key=args.api_key,
        allow_unsafe_bind=args.allow_unsafe_bind,
        check=args.check,
    )
    return server_main(argv)


def run_mcp(args, *, ctx: RuntimeCliContext) -> int:
    """Launch the local Cortex MCP server over stdio."""
    from cortex.mcp.mcp import main as mcp_main

    if getattr(args, "subcommand", "") == "mcp":
        ctx.emit_compatibility_note("mcp", "cortex serve mcp", format_name=getattr(args, "format", None))

    if args.check and args.format == "json":
        try:
            config, selection = _load_runtime_check_config(
                ctx,
                command="serve mcp",
                store_dir=args.store_dir,
                context_file=args.context_file,
                config_path=args.config,
                namespace=args.namespace,
            )
            payload = _serve_check_payload(
                target="mcp",
                mode="mcp",
                config=config,
                selection=selection,
            )
        except ValueError as exc:
            return ctx.error(str(exc))
        ctx.emit_result(payload, "json")
        return 0

    try:
        _config, selection = _load_runtime_check_config(
            ctx,
            command="serve mcp",
            store_dir=args.store_dir,
            context_file=args.context_file,
            config_path=args.config,
            namespace=args.namespace,
        )
    except ValueError as exc:
        return ctx.error(str(exc))
    for warning in selection.warnings:
        ctx.echo(f"Warning: {warning}", stderr=True)
    argv = ctx.runtime_forward_argv(
        selection=selection,
        explicit_config_path=args.config,
        context_file=args.context_file,
        namespace=args.namespace,
        check=args.check,
    )
    return mcp_main(argv)


__all__ = [
    "RuntimeCliContext",
    "run_connect_runtime_target",
    "run_mcp",
    "run_server",
    "run_ui",
]
