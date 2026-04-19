#!/usr/bin/env python3
"""
Cortex CLI — own your AI context and take it everywhere.

Usage:
    cortex portable chatgpt-export.zip --to all
    cortex extract chatgpt-export.zip -o context.json
    cortex import context.json --to notion -o ./output
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from cortex import agent as agent_module
from cortex import cli_entrypoint as cli_entrypoint_module
from cortex import cli_extract_commands as cli_extract_commands_module
from cortex import cli_graph_commands as cli_graph_commands_module
from cortex import cli_mind_pack_commands as cli_mind_pack_commands_module
from cortex import cli_misc_commands as cli_misc_commands_module
from cortex import cli_parser as cli_parser_module
from cortex import cli_portable_commands as cli_portable_commands_module
from cortex import cli_runtime_commands as cli_runtime_commands_module
from cortex import cli_surface as cli_surface_module
from cortex import cli_workspace_commands as cli_workspace_commands_module

ADVANCED_HELP_NOTE = cli_surface_module.ADVANCED_HELP_NOTE
CONNECT_RUNTIME_TARGETS = cli_surface_module.CONNECT_RUNTIME_TARGETS
FIRST_CLASS_COMMANDS = cli_surface_module.FIRST_CLASS_COMMANDS
GOVERNANCE_ACTION_CHOICES = cli_parser_module.GOVERNANCE_ACTION_CHOICES
PLATFORM_FORMATS = cli_parser_module.PLATFORM_FORMATS
format_cli_error = cli_surface_module.format_cli_error
_doctor_has_store_signature = cli_workspace_commands_module._doctor_has_store_signature
_doctor_is_cortex_config = cli_workspace_commands_module._doctor_is_cortex_config
_doctor_raw_config_payload = cli_workspace_commands_module._doctor_raw_config_payload
_doctor_store_entries = cli_workspace_commands_module._doctor_store_entries

_CLI_QUIET = False

CLI_V2_TIER2_NAMESPACES = (
    "mind",
    "pack",
    "source",
    "audience",
    "remote",
    "governance",
    "extract",
    "serve",
    "admin",
    "debug",
)
CLI_HELP_TIER1_VERBS = (
    "init",
    "remember",
    "mount",
    "sync",
    "compose",
    "status",
    "commit",
    "branch",
    "merge",
    "log",
    "diff",
    "verify",
)


def _internal_command(command: str) -> str:
    return cli_parser_module.CLI_V2_INTERNAL_COMMANDS[command][0]


CLI_V2_ROUTES: dict[tuple[str, ...], tuple[str, ...]] = {
    ("compose",): (_internal_command("context-export"),),
    ("source", "ingest"): (_internal_command("ingest"),),
    ("source", "list"): ("sources", "list"),
    ("source", "retract"): ("sources", "retract"),
    ("source", "status"): ("scan",),
    ("extract", "run"): (_internal_command("extract"),),
    ("extract", "ab"): (_internal_command("extract-ab"),),
    ("extract", "benchmark"): (_internal_command("extract-benchmark"),),
    ("extract", "coding"): (_internal_command("extract-coding"),),
    ("extract", "eval"): (_internal_command("extract-eval"),),
    ("extract", "refresh-cache"): (_internal_command("extract-refresh-cache"),),
    ("extract", "review"): (_internal_command("extract-review"),),
    ("extract", "trace"): (_internal_command("extract-trace"),),
    ("branch", "switch"): (_internal_command("switch"),),
    ("mount", "hook"): (_internal_command("context-hook"),),
    ("admin", "doctor"): (_internal_command("doctor"),),
    ("admin", "integrity"): (_internal_command("integrity"),),
    ("admin", "rehash"): (_internal_command("integrity"), "rehash"),
    ("admin", "backup"): (_internal_command("backup"),),
    ("admin", "restore"): (_internal_command("backup"), "restore"),
    ("admin", "rotate"): (_internal_command("rotate"),),
    ("admin", "completion"): (_internal_command("completion"),),
    ("admin", "openapi"): (_internal_command("openapi"),),
    ("admin", "benchmark"): (_internal_command("benchmark"),),
    ("admin", "release-notes"): (_internal_command("release-notes"),),
    ("admin", "migrate"): (_internal_command("migrate"),),
    ("admin", "identity"): (_internal_command("identity"),),
    ("admin", "agent"): (_internal_command("agent"),),
    ("debug", "viz"): (_internal_command("viz"),),
    ("debug", "timeline"): (_internal_command("timeline"),),
    ("debug", "digest"): (_internal_command("digest"),),
    ("debug", "gaps"): (_internal_command("gaps"),),
    ("debug", "watch"): (_internal_command("watch"),),
    ("debug", "extractions", "tail"): (_internal_command("extractions-tail"),),
    ("debug", "query"): (_internal_command("query"),),
    ("debug", "blame"): (_internal_command("blame"),),
    ("debug", "history"): (_internal_command("history"),),
    ("debug", "claims"): (_internal_command("claim"),),
    ("debug", "contradictions"): (_internal_command("contradictions"),),
    ("debug", "drift"): (_internal_command("drift"),),
    ("debug", "review"): (_internal_command("review"),),
    ("debug", "stats"): (_internal_command("stats"),),
    ("mind", "switch"): ("mind", "default"),
    ("mind", "attach"): ("mind", "attach-pack"),
    ("mind", "detach"): ("mind", "detach-pack"),
    ("pack", "publish"): ("pack", "export"),
    ("governance", "remove"): ("governance", "delete"),
}
CLI_V2_ROUTES.update(
    {(command,): (internal,) for command, (internal, _display) in cli_parser_module.CLI_V2_INTERNAL_COMMANDS.items()}
)

# ---------------------------------------------------------------------------
# Export dispatch table: format-key → (export_fn, filename, is_json)
# ---------------------------------------------------------------------------
EXPORT_DISPATCH = {
    # Populated lazily via _export_dispatch() so portability-first CLI commands
    # do not pay the import cost of the full export stack.
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _echo(message: str = "", *, stderr: bool = False, force: bool = False) -> None:
    if _CLI_QUIET and not stderr and not force:
        return
    print(message, file=sys.stderr if stderr else sys.stdout)


def _error(message: str, *, hint: str | None = None, code: int = 1) -> int:
    _echo(format_cli_error(message, hint=hint), stderr=True, force=True)
    return code


def _missing_path_error(path: Path, *, label: str = "File") -> int:
    return _error(f"{label} not found: {path}", hint="Check the path and try again.")


def _permission_error(path: Path, *, action: str) -> int:
    return _error(
        f"Permission denied while trying to {action}: {path}",
        hint="Check file permissions or choose a writable location.",
    )


def _no_context_error() -> int:
    return _error(
        "No portability context found yet.",
        hint="Run `cortex portable <export-or-graph> --to all --project .`, `cortex build`, or `cortex remember` first.",
    )


def _extract_global_flags(argv: list[str]) -> tuple[list[str], bool, bool]:
    cleaned: list[str] = []
    force_json = False
    quiet = False
    for token in argv:
        if token == "--json":
            force_json = True
            continue
        if token == "--quiet":
            quiet = True
            continue
        cleaned.append(token)
    return cleaned, force_json, quiet


def _route_cli_v2_argv(argv: list[str]) -> tuple[list[str], bool]:
    for route, replacement in sorted(CLI_V2_ROUTES.items(), key=lambda item: len(item[0]), reverse=True):
        if tuple(argv[: len(route)]) == route:
            return [*replacement, *argv[len(route) :]], True
    return argv, False


def _subparser_action(parser) -> argparse._SubParsersAction | None:
    return next((item for item in parser._actions if isinstance(item, argparse._SubParsersAction)), None)


def _visible_choice_actions(action: argparse._SubParsersAction) -> dict[str, Any]:
    return {
        choice.dest: choice
        for choice in action._choices_actions
        if choice.dest and choice.help is not argparse.SUPPRESS and not choice.dest.startswith("__cli_v2_")
    }


def _choice_help(choice) -> str:
    help_text = getattr(choice, "help", "") or "No description available."
    return " ".join(str(help_text).strip().split())


def _namespace_subcommands(parser) -> list[str]:
    action = _subparser_action(parser)
    if action is None:
        return []
    visible = _visible_choice_actions(action)
    return [name for name in action.choices if name in visible]


def _format_help_tree(parser=None) -> str:
    parser = parser or build_parser()
    action = _subparser_action(parser)
    if action is None:
        return parser.format_help()
    choices = _visible_choice_actions(action)

    lines = [
        "Cortex help tree",
        "",
        "Tier 1 verbs:",
    ]
    for command in CLI_HELP_TIER1_VERBS:
        choice = choices.get(command)
        if choice is None:
            continue
        lines.append(f"  {command:<10} {_choice_help(choice)}")

    lines.extend(["", "Namespaces:"])
    for namespace in CLI_V2_TIER2_NAMESPACES:
        choice = choices.get(namespace)
        namespace_parser = action.choices.get(namespace)
        if choice is None or namespace_parser is None:
            continue
        subcommands = _namespace_subcommands(namespace_parser)
        subcommand_text = ", ".join(subcommands) if subcommands else "(no subcommands)"
        lines.append(f"  {namespace:<10} {_choice_help(choice)}")
        lines.append(f"             {subcommand_text}")

    alias_names = ("connect", "rollback", "scan", "checkout", "sources", "pull")
    aliases = [name for name in alias_names if name in choices]
    if aliases:
        lines.extend(["", f"Permanent aliases: {', '.join(aliases)}"])

    lines.extend(
        [
            "",
            "Use `cortex <verb> --help` or `cortex <namespace> <subcommand> --help` for details.",
            "Use `cortex help init`, `cortex help runtime`, or `cortex help legacy` for guided topics.",
            "",
        ]
    )
    return "\n".join(lines)


def _resolve_store_selection(store_dir: str | Path | None):
    from cortex.config import CortexStoreDiscovery, resolve_cli_store_dir

    selection = resolve_cli_store_dir(store_dir, cwd=Path.cwd(), env=os.environ)
    warnings = list(selection.warnings)
    if selection.config_path and selection.config_path.parent.name == ".cortex":
        canonical_store = selection.config_path.parent.resolve()
        if selection.store_dir.resolve() != canonical_store:
            warnings.append(
                f"{selection.config_path} resolves store_dir to {selection.store_dir.resolve()}, not the canonical {canonical_store}. "
                "Run `cortex doctor --fix` to normalize it."
            )
    if warnings == list(selection.warnings):
        return selection
    return CortexStoreDiscovery(
        store_dir=selection.store_dir,
        source=selection.source,
        config_path=selection.config_path,
        warnings=tuple(warnings),
    )


def _resolve_first_class_store_selection(store_dir: str | Path | None, *, command: str):
    from cortex.config import CortexStoreDiscovery

    selection = _resolve_store_selection(store_dir)
    if store_dir is None:
        return selection

    raw = str(store_dir).strip()
    if not raw:
        return selection

    explicit = Path(raw).expanduser()
    resolved = explicit if explicit.is_absolute() else (Path.cwd() / explicit)
    resolved = resolved.resolve()
    if resolved.name == ".cortex":
        return selection

    root_entries = _doctor_store_entries(resolved)
    root_config_path = resolved / "config.toml"
    root_config_payload, root_config_error = _doctor_raw_config_payload(root_config_path)
    if _doctor_has_store_signature(root_entries) or root_config_error or _doctor_is_cortex_config(root_config_payload):
        raise ValueError(
            f"Refusing to use {resolved} as the active store for `cortex {command}`. "
            "First-class Cortex CLI flows expect the canonical `.cortex/` layout. "
            f"Run `cortex doctor --store-dir {resolved} --fix-store` or pass {resolved / '.cortex'} explicitly."
        )

    canonical_store = (resolved / ".cortex").resolve()
    warnings = list(selection.warnings)
    warnings.append(
        f"Interpreting explicit store path {resolved} as a workspace root; using {canonical_store} as the canonical `.cortex` store."
    )
    config_path = (canonical_store / "config.toml").resolve() if (canonical_store / "config.toml").exists() else None
    return CortexStoreDiscovery(
        store_dir=canonical_store,
        source="cli_workspace",
        config_path=config_path,
        warnings=tuple(warnings),
    )


def _resolved_store_dir(store_dir: str | Path | None) -> Path:
    return _resolve_store_selection(store_dir).store_dir


def _load_first_class_runtime_config(
    *,
    command: str,
    store_dir: str | Path | None = None,
    context_file: str | Path | None = None,
    config_path: str | Path | None = None,
    host: str | None = None,
    port: int | None = None,
    runtime_mode: str | None = None,
    namespace: str | None = None,
    api_key: str | None = None,
):
    from cortex.config import CortexStoreDiscovery, load_selfhost_config

    explicit_config = Path(config_path).expanduser().resolve() if config_path else None
    if explicit_config is not None:
        config = load_selfhost_config(
            store_dir=store_dir,
            context_file=context_file,
            config_path=explicit_config,
            server_host=host,
            server_port=port,
            runtime_mode=runtime_mode,
            mcp_namespace=namespace,
            api_key=api_key,
            env={},
        )
        selection = CortexStoreDiscovery(
            store_dir=config.store_dir.resolve(),
            source="explicit_config",
            config_path=config.config_path,
            warnings=tuple(),
        )
        return config, selection

    selection = _resolve_first_class_store_selection(store_dir, command=command)
    config = load_selfhost_config(
        store_dir=selection.store_dir,
        context_file=context_file,
        config_path=selection.config_path,
        server_host=host,
        server_port=port,
        runtime_mode=runtime_mode,
        mcp_namespace=namespace,
        api_key=api_key,
        env={},
    )
    return config, selection


def _runtime_forward_argv(
    *,
    selection,
    explicit_config_path: str | None = None,
    context_file: str | None = None,
    namespace: str | None = None,
    host: str | None = None,
    port: int | None = None,
    runtime_mode: str | None = None,
    api_key: str | None = None,
    allow_unsafe_bind: bool = False,
    allow_write_tools: bool = False,
    tools: list[str] | tuple[str, ...] = (),
    protocol_version: str | None = None,
    check: bool = False,
):
    argv: list[str] = []
    config_arg = explicit_config_path or (str(selection.config_path) if selection.config_path else None)
    if config_arg:
        argv.extend(["--config", config_arg])
    else:
        argv.extend(["--store-dir", str(selection.store_dir)])
    if context_file:
        argv.extend(["--context-file", context_file])
    if namespace:
        argv.extend(["--namespace", namespace])
    if host:
        argv.extend(["--host", host])
    if port is not None:
        argv.extend(["--port", str(port)])
    if runtime_mode:
        argv.extend(["--runtime-mode", runtime_mode])
    if api_key:
        argv.extend(["--api-key", api_key])
    if allow_unsafe_bind:
        argv.append("--allow-unsafe-bind")
    if allow_write_tools:
        argv.append("--allow-write-tools")
    for tool in tools:
        argv.extend(["--tool", tool])
    if protocol_version:
        argv.extend(["--protocol-version", protocol_version])
    if check:
        argv.append("--check")
    return argv


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _emit_compatibility_note(command: str, modern_path: str, *, note: str = "", format_name: str | None = None) -> None:
    if _CLI_QUIET:
        return
    if format_name == "json":
        return
    message = f"Compatibility note: `cortex {command}` still works, but the first-class path is `{modern_path}`."
    if note:
        message += f" {note}"
    _echo(message, stderr=True)


def _runtime_cli_context() -> cli_runtime_commands_module.RuntimeCliContext:
    return cli_runtime_commands_module.RuntimeCliContext(
        emit_result=_emit_result,
        echo=_echo,
        error=_error,
        emit_compatibility_note=_emit_compatibility_note,
        load_first_class_runtime_config=_load_first_class_runtime_config,
        runtime_forward_argv=_runtime_forward_argv,
        shell_join=_shell_join,
    )


def _workspace_cli_context() -> cli_workspace_commands_module.WorkspaceCliContext:
    return cli_workspace_commands_module.WorkspaceCliContext(
        emit_result=_emit_result,
        echo=_echo,
        error=_error,
        emit_compatibility_note=_emit_compatibility_note,
        resolve_first_class_store_selection=_resolve_first_class_store_selection,
        resolve_store_selection=_resolve_store_selection,
        resolved_store_dir=_resolved_store_dir,
    )


def _portable_cli_context() -> cli_portable_commands_module.PortableCliContext:
    return cli_portable_commands_module.PortableCliContext(
        cli_quiet=_CLI_QUIET,
        emit_result=_emit_result,
        echo=_echo,
        error=_error,
        emit_compatibility_note=_emit_compatibility_note,
        load_graph=_load_graph,
        missing_path_error=_missing_path_error,
        no_context_error=_no_context_error,
        permission_error=_permission_error,
        build_pii_redactor=_build_pii_redactor,
        graph_category_stats=_graph_category_stats,
        load_detected_sources_or_error=_load_detected_sources_or_error,
        run_extraction=_run_extraction,
    )


def _extract_cli_context() -> cli_extract_commands_module.ExtractCliContext:
    return cli_extract_commands_module.ExtractCliContext(
        echo=_echo,
        error=_error,
        is_quiet=lambda: _CLI_QUIET,
        load_graph=_load_graph,
        missing_path_error=_missing_path_error,
        permission_error=_permission_error,
    )


def _misc_cli_context() -> cli_misc_commands_module.MiscCliContext:
    return cli_misc_commands_module.MiscCliContext(
        build_parser=build_parser,
        echo=_echo,
        error=_error,
        missing_path_error=_missing_path_error,
    )


def _agent_cli_context() -> agent_module.AgentCliContext:
    return agent_module.AgentCliContext(
        emit_result=_emit_result,
        echo=_echo,
        error=_error,
        resolved_store_dir=_resolved_store_dir,
    )


def _run_extraction(extractor, data, fmt):
    return cli_extract_commands_module.run_extraction(extractor, data, fmt)


def _emit_result(result, output_format: str) -> int:
    if output_format == "json":
        _echo(json.dumps(result, indent=2), force=True)
        return 0
    if _CLI_QUIET:
        return 0
    return -1


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

build_parser = cli_parser_module.build_parser


def _set_cli_quiet(value: bool) -> None:
    global _CLI_QUIET
    _CLI_QUIET = value


def _entrypoint_cli_context() -> cli_entrypoint_module.EntryPointCliContext:
    handlers = {
        "init": run_init,
        "help": run_help_topic,
        "connect": run_connect,
        "serve": run_serve,
        "diff": run_diff,
        "checkout": run_checkout,
        "rollback": run_rollback,
        "commit": run_commit,
        "branch": run_branch,
        "merge": run_merge,
        "log": run_log,
        "governance": run_governance,
        "remote": run_remote,
        "sync": run_sync,
        "verify": run_verify,
        "pull": run_pull,
        "scan": run_scan,
        "remember": run_remember,
        "status": run_status,
        "mount": run_mount,
        "mind": run_mind,
        "sources": run_sources,
        "audience": run_audience,
        "pack": run_pack,
        _internal_command("extract"): run_extract,
        _internal_command("extract-ab"): run_extract_ab,
        _internal_command("extract-benchmark"): run_extract_benchmark,
        _internal_command("extract-eval"): run_extract_eval,
        _internal_command("extract-refresh-cache"): run_extract_refresh_cache,
        _internal_command("extract-review"): run_extract_review,
        _internal_command("extract-trace"): run_extract_trace,
        _internal_command("ingest"): run_ingest,
        _internal_command("import"): run_import,
        _internal_command("memory"): run_memory,
        _internal_command("migrate"): run_migrate,
        _internal_command("query"): run_query,
        _internal_command("extractions-tail"): run_extractions_tail,
        _internal_command("stats"): run_stats,
        _internal_command("timeline"): run_timeline,
        _internal_command("contradictions"): run_contradictions,
        _internal_command("drift"): run_drift,
        _internal_command("blame"): run_blame,
        _internal_command("history"): run_history,
        _internal_command("claim"): run_claim,
        _internal_command("identity"): run_identity,
        _internal_command("switch"): run_switch,
        _internal_command("review"): run_review,
        _internal_command("gaps"): run_gaps,
        _internal_command("digest"): run_digest,
        _internal_command("viz"): run_viz,
        _internal_command("watch"): run_watch,
        _internal_command("sync-schedule"): run_sync_schedule,
        _internal_command("extract-coding"): run_extract_coding,
        _internal_command("context-hook"): run_context_hook,
        _internal_command("context-export"): run_context_export,
        _internal_command("context-write"): run_context_write,
        _internal_command("portable"): run_portable,
        _internal_command("build"): run_build,
        _internal_command("audit"): run_audit,
        _internal_command("doctor"): run_doctor,
        _internal_command("integrity"): run_integrity,
        _internal_command("ui"): run_ui,
        _internal_command("benchmark"): run_benchmark,
        _internal_command("backup"): run_backup,
        _internal_command("agent"): run_agent,
        _internal_command("openapi"): run_openapi,
        _internal_command("release-notes"): run_release_notes,
        _internal_command("server"): run_server,
        _internal_command("mcp"): run_mcp,
        _internal_command("rotate"): run_rotate,
        _internal_command("completion"): run_completion,
    }
    return cli_entrypoint_module.EntryPointCliContext(
        build_parser=build_parser,
        error=_error,
        extract_global_flags=_extract_global_flags,
        set_cli_quiet=_set_cli_quiet,
        handlers=handlers,
        route_argv=_route_cli_v2_argv,
        format_help_tree=_format_help_tree,
    )


# ---------------------------------------------------------------------------
# Subcommand runners
# ---------------------------------------------------------------------------


def _load_detected_sources_or_error(
    args,
    *,
    project_dir: Path,
    announce: bool = True,
    redactor=None,
) -> dict[str, Any] | None:
    return cli_extract_commands_module.load_detected_sources_or_error(
        args,
        project_dir=project_dir,
        announce=announce,
        redactor=redactor,
        ctx=_extract_cli_context(),
    )


def _graph_category_stats(graph) -> dict[str, Any]:
    return cli_extract_commands_module.graph_category_stats(graph)


def _build_pii_redactor(args, *, default_enabled: bool = False):
    return cli_extract_commands_module.build_pii_redactor(args, default_enabled=default_enabled)


def run_extract(args):
    return cli_extract_commands_module.run_extract(args, ctx=_extract_cli_context())


def run_extract_ab(args):
    return cli_extract_commands_module.run_extract_ab(args, ctx=_extract_cli_context())


def run_extract_benchmark(args):
    return cli_extract_commands_module.run_extract_benchmark(args, ctx=_extract_cli_context())


def run_extract_eval(args):
    return cli_extract_commands_module.run_extract_eval(args, ctx=_extract_cli_context())


def run_extract_refresh_cache(args):
    return cli_extract_commands_module.run_extract_refresh_cache(args, ctx=_extract_cli_context())


def run_extract_review(args):
    return cli_extract_commands_module.run_extract_review(args, ctx=_extract_cli_context())


def run_extract_trace(args):
    return cli_extract_commands_module.run_extract_trace(args, ctx=_extract_cli_context())


def run_ingest(args):
    return cli_extract_commands_module.run_ingest(args, ctx=_extract_cli_context())


def run_import(args):
    return cli_extract_commands_module.run_import(args, ctx=_extract_cli_context())


def run_migrate(args):
    return cli_extract_commands_module.run_migrate(args, ctx=_extract_cli_context())


def _graph_cli_context() -> cli_graph_commands_module.GraphCliContext:
    return cli_graph_commands_module.GraphCliContext(
        emit_result=_emit_result,
        echo=_echo,
        error=_error,
        missing_path_error=_missing_path_error,
    )


_load_graph = cli_graph_commands_module._load_graph
_save_graph = cli_graph_commands_module._save_graph
_parse_properties = cli_graph_commands_module._parse_properties
_load_identity = cli_graph_commands_module._load_identity
_current_branch_or_ref = cli_graph_commands_module._current_branch_or_ref
_governance_decision_or_error = cli_graph_commands_module._governance_decision_or_error
_maybe_commit_graph = cli_graph_commands_module._maybe_commit_graph
_claim_event_from_record = cli_graph_commands_module._claim_event_from_record
_find_claim_target_node = cli_graph_commands_module._find_claim_target_node
_load_claim_or_error = cli_graph_commands_module._load_claim_or_error
_resolve_version_or_exit = cli_graph_commands_module._resolve_version_or_exit
_resolve_version_at_or_exit = cli_graph_commands_module._resolve_version_at_or_exit
_rule_from_args = cli_graph_commands_module._rule_from_args


def run_query(args):
    return cli_graph_commands_module.run_query(args, ctx=_graph_cli_context())


def run_timeline(args):
    return cli_graph_commands_module.run_timeline(args, ctx=_graph_cli_context())


def run_memory_conflicts(args):
    return cli_graph_commands_module.run_memory_conflicts(args, ctx=_graph_cli_context())


def run_memory_show(args):
    return cli_graph_commands_module.run_memory_show(args, ctx=_graph_cli_context())


def run_memory_forget(args):
    return cli_graph_commands_module.run_memory_forget(args, ctx=_graph_cli_context())


def run_memory_set(args):
    return cli_graph_commands_module.run_memory_set(args, ctx=_graph_cli_context())


def run_memory_retract(args):
    return cli_graph_commands_module.run_memory_retract(args, ctx=_graph_cli_context())


def run_blame(args):
    return cli_graph_commands_module.run_blame(args, ctx=_graph_cli_context())


def run_history(args):
    return cli_graph_commands_module.run_history(args, ctx=_graph_cli_context())


def run_claim_accept(args):
    return cli_graph_commands_module.run_claim_accept(args, ctx=_graph_cli_context())


def run_claim_reject(args):
    return cli_graph_commands_module.run_claim_reject(args, ctx=_graph_cli_context())


def run_claim_supersede(args):
    return cli_graph_commands_module.run_claim_supersede(args, ctx=_graph_cli_context())


def run_claim_log(args):
    return cli_graph_commands_module.run_claim_log(args, ctx=_graph_cli_context())


def run_claim_show(args):
    return cli_graph_commands_module.run_claim_show(args, ctx=_graph_cli_context())


def run_memory_resolve(args):
    return cli_graph_commands_module.run_memory_resolve(args, ctx=_graph_cli_context())


def run_contradictions(args):
    return cli_graph_commands_module.run_contradictions(args, ctx=_graph_cli_context())


def run_drift(args):
    return cli_graph_commands_module.run_drift(args, ctx=_graph_cli_context())


def run_diff(args):
    return cli_graph_commands_module.run_diff(args, ctx=_graph_cli_context())


def run_checkout(args):
    return cli_graph_commands_module.run_checkout(args, ctx=_graph_cli_context())


def run_rollback(args):
    return cli_graph_commands_module.run_rollback(args, ctx=_graph_cli_context())


def run_identity(args):
    return cli_graph_commands_module.run_identity(args, ctx=_graph_cli_context())


def run_commit(args):
    return cli_graph_commands_module.run_commit(args, ctx=_graph_cli_context())


def run_branch(args):
    return cli_graph_commands_module.run_branch(args, ctx=_graph_cli_context())


def run_switch(args):
    return cli_graph_commands_module.run_switch(args, ctx=_graph_cli_context())


def run_merge(args):
    return cli_graph_commands_module.run_merge(args, ctx=_graph_cli_context())


def run_review(args):
    return cli_graph_commands_module.run_review(args, ctx=_graph_cli_context())


def run_log(args):
    return cli_graph_commands_module.run_log(args, ctx=_graph_cli_context())


def run_governance(args):
    return cli_graph_commands_module.run_governance(args, ctx=_graph_cli_context())


def run_remote(args):
    return cli_graph_commands_module.run_remote(args, ctx=_graph_cli_context())


def run_sync(args):
    return cli_portable_commands_module.run_sync(args, ctx=_portable_cli_context())


def run_verify(args):
    return cli_portable_commands_module.run_verify(args, ctx=_portable_cli_context())


def run_gaps(args):
    return cli_portable_commands_module.run_gaps(args, ctx=_portable_cli_context())


def run_digest(args):
    return cli_portable_commands_module.run_digest(args, ctx=_portable_cli_context())


def run_viz(args):
    return cli_portable_commands_module.run_viz(args, ctx=_portable_cli_context())


def run_watch(args):
    return cli_portable_commands_module.run_watch(args, ctx=_portable_cli_context())


def run_sync_schedule(args):
    return cli_portable_commands_module.run_sync_schedule(args, ctx=_portable_cli_context())


def run_extract_coding(args):
    return cli_portable_commands_module.run_extract_coding(args, ctx=_portable_cli_context())


def run_context_hook(args):
    return cli_portable_commands_module.run_context_hook(args, ctx=_portable_cli_context())


def run_context_export(args):
    return cli_portable_commands_module.run_context_export(args, ctx=_portable_cli_context())


def run_context_write(args):
    return cli_portable_commands_module.run_context_write(args, ctx=_portable_cli_context())


def run_mount(args):
    return cli_portable_commands_module.run_mount(args, ctx=_portable_cli_context())


def run_portable(args):
    return cli_portable_commands_module.run_portable(args, ctx=_portable_cli_context())


def run_memory(args):
    if args.memory_subcommand == "conflicts":
        return run_memory_conflicts(args)
    if args.memory_subcommand == "show":
        return run_memory_show(args)
    if args.memory_subcommand == "forget":
        return run_memory_forget(args)
    if args.memory_subcommand == "retract":
        return run_memory_retract(args)
    if args.memory_subcommand == "set":
        return run_memory_set(args)
    if args.memory_subcommand == "resolve":
        return run_memory_resolve(args)
    return _error(
        "Missing memory subcommand.",
        hint="Run `cortex memory --help` and choose one of: conflicts, show, forget, retract, set, or resolve.",
    )


def run_claim(args):
    if args.claim_subcommand == "log":
        return run_claim_log(args)
    if args.claim_subcommand == "show":
        return run_claim_show(args)
    if args.claim_subcommand == "accept":
        return run_claim_accept(args)
    if args.claim_subcommand == "reject":
        return run_claim_reject(args)
    if args.claim_subcommand == "supersede":
        return run_claim_supersede(args)
    return _error(
        "Missing claim subcommand.",
        hint="Run `cortex claim --help` and choose one of: log, show, accept, reject, or supersede.",
    )


def _mind_pack_cli_context() -> cli_mind_pack_commands_module.MindPackCliContext:
    return cli_mind_pack_commands_module.MindPackCliContext(
        emit_result=_emit_result,
        echo=_echo,
        error=_error,
        missing_path_error=_missing_path_error,
        build_pii_redactor=_build_pii_redactor,
        resolved_store_dir=_resolved_store_dir,
    )


def run_pack(args):
    return cli_mind_pack_commands_module.run_pack(args, ctx=_mind_pack_cli_context())


def run_mind(args):
    return cli_mind_pack_commands_module.run_mind(args, ctx=_mind_pack_cli_context())


def run_sources(args):
    return cli_mind_pack_commands_module.run_sources(args, ctx=_mind_pack_cli_context())


def run_audience(args):
    return cli_mind_pack_commands_module.run_audience(args, ctx=_mind_pack_cli_context())


def run_init(args):
    return cli_workspace_commands_module.run_init(args, ctx=_workspace_cli_context())


def run_help_topic(args):
    if getattr(args, "topic", None) is None:
        _echo(_format_help_tree(), force=True)
        return 0
    return cli_workspace_commands_module.run_help_topic(args, ctx=_workspace_cli_context())


def run_scan(args):
    return cli_workspace_commands_module.run_scan(args, ctx=_workspace_cli_context())


def run_remember(args):
    return cli_workspace_commands_module.run_remember(args, ctx=_workspace_cli_context())


def run_status(args):
    return cli_workspace_commands_module.run_status(args, ctx=_workspace_cli_context())


def run_build(args):
    return cli_workspace_commands_module.run_build(args, ctx=_workspace_cli_context())


def run_audit(args):
    return cli_workspace_commands_module.run_audit(args, ctx=_workspace_cli_context())


def run_doctor(args):
    return cli_workspace_commands_module.run_doctor(args, ctx=_workspace_cli_context())


def run_integrity(args):
    if args.integrity_subcommand in {"check", "rehash"}:
        return cli_graph_commands_module.run_integrity(args, ctx=_graph_cli_context())
    return _error(
        "Missing integrity subcommand.",
        hint="Run `cortex integrity --help` and choose `check` or `rehash`.",
    )


def run_connect_manus(args):
    return cli_runtime_commands_module.run_connect_manus(args, ctx=_runtime_cli_context())


def run_connect_runtime_target(args, *, target: str):
    return cli_runtime_commands_module.run_connect_runtime_target(args, target=target, ctx=_runtime_cli_context())


def run_connect(args):
    if args.connect_subcommand == "manus":
        return run_connect_manus(args)
    if args.connect_subcommand in CONNECT_RUNTIME_TARGETS:
        return run_connect_runtime_target(args, target=args.connect_subcommand)
    return _error(
        "Missing connect target.",
        hint="Run `cortex connect --help` and pick manus, hermes, codex, cursor, or claude-code.",
    )


def run_serve_manus(args):
    return cli_runtime_commands_module.run_serve_manus(args, ctx=_runtime_cli_context())


def run_serve(args):
    if args.serve_subcommand == "api":
        return run_server(args)
    if args.serve_subcommand == "mcp":
        return run_mcp(args)
    if args.serve_subcommand == "manus":
        return run_serve_manus(args)
    if args.serve_subcommand == "ui":
        return run_ui(args)
    return _error(
        "Missing serve target.",
        hint="Run `cortex serve --help` and choose api, mcp, manus, or ui.",
    )


def run_ui(args):
    return cli_runtime_commands_module.run_ui(args, ctx=_runtime_cli_context())


def run_server(args):
    return cli_runtime_commands_module.run_server(args, ctx=_runtime_cli_context())


def run_mcp(args):
    return cli_runtime_commands_module.run_mcp(args, ctx=_runtime_cli_context())


def run_openapi(args):
    """Write the OpenAPI contract to disk."""
    from cortex.service.openapi import write_openapi_spec

    output_path = write_openapi_spec(args.output, server_url=args.server_url, compat_output_path=args.compat_output)
    print(f"Wrote OpenAPI spec to {output_path}")
    if args.compat_output:
        print(f"Wrote OpenAPI compatibility snapshot to {args.compat_output}")
    return 0


def run_release_notes(args):
    """Write Markdown release notes and a JSON release manifest."""
    from cortex.release import write_release_manifest, write_release_notes
    from cortex.service.openapi import build_openapi_spec

    spec = build_openapi_spec()
    notes_path = write_release_notes(args.output, spec, tag=args.tag, commit_sha=args.commit_sha)
    manifest_path = write_release_manifest(args.manifest_output, spec, tag=args.tag, commit_sha=args.commit_sha)
    print(f"Wrote release notes to {notes_path}")
    print(f"Wrote release manifest to {manifest_path}")
    return 0


def run_benchmark(args):
    """Run the lightweight self-host benchmark harness."""
    from cortex.benchmark import main as benchmark_main

    argv = [
        "--store-dir",
        args.store_dir,
        "--iterations",
        str(args.iterations),
        "--nodes",
        str(args.nodes),
    ]
    if args.output:
        argv.extend(["--output", args.output])
    return benchmark_main(argv)


def _default_backup_output() -> str:
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return str(Path("backups") / f"cortex-store-{timestamp}.zip")


def run_backup_export(args):
    from cortex.backup import export_store_backup

    result = export_store_backup(
        args.store_dir,
        args.output or _default_backup_output(),
        verify=not args.no_verify,
    )
    print(json.dumps(result, indent=2))
    return 0


def run_backup_verify(args):
    from cortex.backup import verify_store_backup

    result = verify_store_backup(args.archive)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


def run_backup_restore(args):
    from cortex.backup import restore_store_backup

    result = restore_store_backup(
        args.archive,
        args.store_dir,
        verify=not args.skip_verify,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    return 0


def run_backup(args):
    if args.backup_subcommand == "export":
        return run_backup_export(args)
    if args.backup_subcommand == "verify":
        return run_backup_verify(args)
    if args.backup_subcommand in {"restore", "import"}:
        return run_backup_restore(args)
    return _error(
        "Missing backup subcommand.",
        hint="Run `cortex backup --help` and choose export, verify, restore, or import.",
    )


def run_stats(args):
    return cli_misc_commands_module.run_stats(args, ctx=_misc_cli_context())


def run_extractions_tail(args):
    return cli_misc_commands_module.run_extractions_tail(args, ctx=_misc_cli_context())


def run_pull(args):
    return cli_misc_commands_module.run_pull(args, ctx=_misc_cli_context())


def run_rotate(args):
    return cli_misc_commands_module.run_rotate(args, ctx=_misc_cli_context())


def run_completion(args):
    if getattr(args, "candidates", ""):
        from cortex.completion import completion_candidates

        values = completion_candidates(
            args.candidates,
            store_dir=getattr(args, "store_dir", ".cortex"),
            mind=getattr(args, "mind", ""),
        )
        for value in values:
            _echo(value, force=True)
        return 0
    return cli_misc_commands_module.run_completion(args, ctx=_misc_cli_context())


def run_agent(args):
    return agent_module.run_agent(args, ctx=_agent_cli_context())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv=None):
    return cli_entrypoint_module.main(argv, ctx=_entrypoint_cli_context())


if __name__ == "__main__":
    sys.exit(main())
