#!/usr/bin/env python3
"""
Cortex CLI — own your AI context and take it everywhere.

Usage:
    cortex portable chatgpt-export.zip --to all
    cortex extract chatgpt-export.zip -o context.json
    cortex import context.json --to notion -o ./output
"""

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from cortex import cli_entrypoint as cli_entrypoint_module
from cortex import cli_graph_commands as cli_graph_commands_module
from cortex import cli_mind_pack_commands as cli_mind_pack_commands_module
from cortex import cli_misc_commands as cli_misc_commands_module
from cortex import cli_parser as cli_parser_module
from cortex import cli_portable_commands as cli_portable_commands_module
from cortex import cli_runtime_commands as cli_runtime_commands_module
from cortex import cli_surface as cli_surface_module
from cortex import cli_workspace_commands as cli_workspace_commands_module
from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory import (
    AggressiveExtractor,
    PIIRedactor,
    build_eval_compat_view,
    load_file,
    merge_contexts,
)
from cortex.graph import CortexGraph

ADVANCED_HELP_NOTE = cli_surface_module.ADVANCED_HELP_NOTE
CONNECT_RUNTIME_TARGETS = cli_surface_module.CONNECT_RUNTIME_TARGETS
FIRST_CLASS_COMMANDS = cli_surface_module.FIRST_CLASS_COMMANDS
GOVERNANCE_ACTION_CHOICES = cli_parser_module.GOVERNANCE_ACTION_CHOICES
PLATFORM_FORMATS = cli_parser_module.PLATFORM_FORMATS
_doctor_has_store_signature = cli_workspace_commands_module._doctor_has_store_signature
_doctor_is_cortex_config = cli_workspace_commands_module._doctor_is_cortex_config
_doctor_raw_config_payload = cli_workspace_commands_module._doctor_raw_config_payload
_doctor_store_entries = cli_workspace_commands_module._doctor_store_entries

_CLI_QUIET = False

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
    _echo(f"Error: {message}", stderr=True, force=True)
    if hint:
        _echo(f"Hint: {hint}", stderr=True, force=True)
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


def _misc_cli_context() -> cli_misc_commands_module.MiscCliContext:
    return cli_misc_commands_module.MiscCliContext(
        build_parser=build_parser,
        echo=_echo,
        error=_error,
        missing_path_error=_missing_path_error,
    )


def _export_dispatch() -> dict[str, tuple[object, str, bool]]:
    from cortex.import_memory import (
        export_claude_memories,
        export_claude_preferences,
        export_full_json,
        export_google_docs,
        export_notion,
        export_notion_database_json,
        export_summary,
        export_system_prompt,
    )

    return {
        "claude-preferences": (export_claude_preferences, "claude_preferences.txt", False),
        "claude-memories": (export_claude_memories, "claude_memories.json", True),
        "system-prompt": (export_system_prompt, "system_prompt.txt", False),
        "notion": (export_notion, "notion_page.md", False),
        "notion-db": (export_notion_database_json, "notion_database.json", True),
        "gdocs": (export_google_docs, "google_docs.html", False),
        "summary": (export_summary, "summary.md", False),
        "full": (export_full_json, "full_export.json", True),
    }


def _confidence_thresholds() -> dict[str, float]:
    from cortex.import_memory import CONFIDENCE_THRESHOLDS

    return CONFIDENCE_THRESHOLDS


def _normalized_context_cls():
    from cortex.import_memory import NormalizedContext

    return NormalizedContext


def _run_extraction(extractor, data, fmt):
    """Route *data* through the correct extractor method and return the v4 dict."""
    if fmt == "openai":
        extractor.process_openai_export(data)
    elif fmt == "gemini":
        extractor.process_gemini_export(data)
    elif fmt == "perplexity":
        extractor.process_perplexity_export(data)
    elif fmt == "grok":
        extractor.process_grok_export(data)
    elif fmt == "cursor":
        extractor.process_cursor_export(data)
    elif fmt == "windsurf":
        extractor.process_windsurf_export(data)
    elif fmt == "copilot":
        extractor.process_copilot_export(data)
    elif fmt in ("jsonl", "claude_code"):
        extractor.process_jsonl_messages(data)
    elif fmt == "api_logs":
        extractor.process_api_logs(data)
    elif fmt == "messages":
        extractor.process_messages_list(data)
    elif fmt == "text":
        extractor.process_plain_text(data)
    else:
        if isinstance(data, list):
            extractor.process_messages_list(data)
        elif isinstance(data, dict) and "messages" in data:
            extractor.process_messages_list(data["messages"])
        else:
            extractor.process_plain_text(json.dumps(data) if not isinstance(data, str) else data)

    extractor.post_process()
    return extractor.context.export()


def _write_exports(ctx, min_conf, format_keys, output_dir, verbose=False):
    """Write the requested formats to *output_dir*. Returns list of (label, path)."""
    export_dispatch = _export_dispatch()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for key in format_keys:
        export_fn, filename, is_json = export_dispatch[key]
        path = output_dir / filename
        result = export_fn(ctx, min_conf)
        if is_json:
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        else:
            path.write_text(result, encoding="utf-8")
        outputs.append((key, path))
        if verbose:
            print(f"   wrote {path}")
    return outputs


def _finalize_extraction_output(
    v4_output: dict,
    *,
    input_path: Path,
    fmt: str,
    store_dir: Path | None = None,
    record_claims: bool = True,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[dict, int]:
    from cortex.claims import extraction_source_label, record_graph_claims, stamp_graph_provenance
    from cortex.storage import get_storage_backend

    graph = upgrade_v4_to_v5(v4_output)
    source = extraction_source_label(input_path)
    claim_count = 0
    metadata = {"input_format": fmt, "input_file": str(input_path)}
    metadata.update(dict(extra_metadata or {}))

    if record_claims:
        stamp_graph_provenance(
            graph,
            source=source,
            method="extract",
            metadata=metadata,
        )
        if store_dir is not None:
            ledger = get_storage_backend(store_dir).claims
            events = record_graph_claims(
                graph,
                ledger,
                op="assert",
                source=source,
                method="extract",
                metadata=metadata,
            )
            claim_count = len(events)

    result = graph.export_v4()
    if "conflicts" in v4_output:
        result["conflicts"] = list(v4_output.get("conflicts", []))
    if "redaction_summary" in v4_output:
        result["redaction_summary"] = v4_output["redaction_summary"]
    result.update(build_eval_compat_view(result))
    return result, claim_count


def _to_context_json_v5(data: dict) -> dict:
    """Normalize extraction output into the pinned portable context.json format."""
    return upgrade_v4_to_v5(data).export_v5()


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
    return cli_entrypoint_module.EntryPointCliContext(
        build_parser=build_parser,
        error=_error,
        extract_global_flags=_extract_global_flags,
        set_cli_quiet=_set_cli_quiet,
        handlers={
            "init": run_init,
            "help": run_help_topic,
            "connect": run_connect,
            "serve": run_serve,
            "extract": run_extract,
            "ingest": run_ingest,
            "import": run_import,
            "memory": run_memory,
            "query": run_query,
            "stats": run_stats,
            "timeline": run_timeline,
            "contradictions": run_contradictions,
            "drift": run_drift,
            "diff": run_diff,
            "blame": run_blame,
            "history": run_history,
            "claim": run_claim,
            "checkout": run_checkout,
            "rollback": run_rollback,
            "identity": run_identity,
            "commit": run_commit,
            "branch": run_branch,
            "switch": run_switch,
            "merge": run_merge,
            "review": run_review,
            "log": run_log,
            "governance": run_governance,
            "remote": run_remote,
            "sync": run_sync,
            "verify": run_verify,
            "gaps": run_gaps,
            "digest": run_digest,
            "viz": run_viz,
            "watch": run_watch,
            "sync-schedule": run_sync_schedule,
            "extract-coding": run_extract_coding,
            "context-hook": run_context_hook,
            "context-export": run_context_export,
            "pull": run_pull,
            "rotate": run_rotate,
            "context-write": run_context_write,
            "portable": run_portable,
            "scan": run_scan,
            "remember": run_remember,
            "status": run_status,
            "build": run_build,
            "audit": run_audit,
            "doctor": run_doctor,
            "mind": run_mind,
            "pack": run_pack,
            "ui": run_ui,
            "benchmark": run_benchmark,
            "backup": run_backup,
            "openapi": run_openapi,
            "release-notes": run_release_notes,
            "server": run_server,
            "mcp": run_mcp,
            "completion": run_completion,
            "migrate": run_migrate,
        },
    )


# ---------------------------------------------------------------------------
# Subcommand runners
# ---------------------------------------------------------------------------


def _load_detected_sources_or_error(
    args,
    *,
    project_dir: Path,
    announce: bool = True,
    redactor: PIIRedactor | None = None,
) -> dict[str, Any] | None:
    detected_selection = list(getattr(args, "from_detected", []) or [])
    if not detected_selection:
        return None

    from cortex.portable_runtime import extract_graph_from_detected_sources

    if announce:
        _echo("Loading detected local sources")
    try:
        detected_payload = extract_graph_from_detected_sources(
            targets=detected_selection,
            store_dir=Path(args.store_dir),
            project_dir=project_dir,
            extra_roots=[Path(root) for root in getattr(args, "search_root", [])],
            include_config_metadata=bool(getattr(args, "include_config_metadata", False)),
            include_unmanaged_text=bool(getattr(args, "include_unmanaged_text", False)),
            redactor=redactor,
        )
    except Exception as exc:
        raise ValueError(str(exc)) from exc

    selected_sources = detected_payload["selected_sources"]
    if selected_sources:
        return detected_payload

    skipped = detected_payload["skipped_sources"]
    metadata_hint = (
        " Add `--include-config-metadata` if you want MCP setup metadata too."
        if any(item.get("reason") == "metadata_only" for item in skipped)
        else ""
    )
    unmanaged_hint = (
        " Add `--include-unmanaged-text` if you want to ingest text outside Cortex markers from instruction files."
        if any(item.get("reason") == "unmanaged_only" for item in skipped)
        else ""
    )
    raise ValueError(
        "No detected sources were approved for extraction.\n"
        f"Hint: Run `cortex scan` first and select an adoptable target.{metadata_hint}{unmanaged_hint}"
    )


def _graph_category_stats(graph: CortexGraph) -> dict[str, Any]:
    categories = graph.export_v4().get("categories", {})
    return {
        "total": sum(len(items) for items in categories.values()),
        "by_category": {name: len(items) for name, items in categories.items()},
    }


def _build_pii_redactor(args, *, default_enabled: bool = False) -> PIIRedactor | None:
    enabled = bool(getattr(args, "redact", False) or default_enabled)
    if not enabled:
        return None

    custom_patterns = None
    patterns_path = getattr(args, "redact_patterns", None)
    if patterns_path:
        pp = Path(patterns_path)
        if not pp.exists():
            raise FileNotFoundError(pp)
        with pp.open("r", encoding="utf-8") as handle:
            custom_patterns = json.load(handle)
    return PIIRedactor(custom_patterns)


def run_extract(args):
    """Extract context from an export file and save as JSON."""
    detected_selection = list(getattr(args, "from_detected", []) or [])
    project_dir = Path(args.project) if getattr(args, "project", None) else Path.cwd()

    if detected_selection and args.input_file:
        return _error("Use either an input file or `--from-detected`, not both.")
    if not detected_selection and not args.input_file:
        return _error("Provide an export file or use `--from-detected`.")

    input_path: Path | None = None
    fmt = "detected" if detected_selection else "auto"
    detected_payload: dict[str, Any] | None = None
    try:
        redactor = _build_pii_redactor(
            args,
            default_enabled=bool(detected_selection and not getattr(args, "no_redact_detected", False)),
        )
    except FileNotFoundError as exc:
        return _missing_path_error(Path(exc.args[0]), label="Redaction patterns file")

    if redactor is not None and not bool(getattr(args, "json_output", False)):
        if detected_selection and not args.redact:
            _echo("PII redaction enabled for detected local sources")
        else:
            _echo("PII redaction enabled")

    if detected_selection:
        try:
            detected_payload = _load_detected_sources_or_error(
                args,
                project_dir=project_dir,
                announce=not _CLI_QUIET and not bool(getattr(args, "json_output", False)),
                redactor=redactor,
            )
        except ValueError as exc:
            lines = str(exc).splitlines()
            return _error(lines[0], hint="\n".join(lines[1:]) or None)
        selected_sources = detected_payload["selected_sources"]
        result = detected_payload["graph"].export_v4()
        input_path = project_dir / "detected_sources.json"
        if not bool(getattr(args, "json_output", False)):
            _echo(
                f"Detected sources: {len(selected_sources)} selected, "
                f"{len(detected_payload['skipped_sources'])} skipped"
            )
    else:
        input_path = Path(args.input_file)
        if not input_path.exists():
            return _missing_path_error(input_path, label="Export file")

        _echo(f"Loading: {input_path}")
        try:
            data, detected_format = load_file(input_path)
        except PermissionError:
            return _permission_error(input_path, action="read the export file")
        except Exception as exc:
            return _error(str(exc))

        fmt = args.format if args.format != "auto" else detected_format
        _echo(f"Format: {fmt}")

    if not detected_selection:
        extractor = AggressiveExtractor(redactor=redactor)

        # Merge
        if args.merge:
            merge_path = Path(args.merge)
            if merge_path.exists():
                _echo(f"Merging with existing context: {merge_path}")
                extractor = merge_contexts(merge_path, extractor)
            else:
                _echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)

        result = _run_extraction(extractor, data, fmt)
        stats = extractor.context.stats()
    else:
        if args.merge:
            merge_path = Path(args.merge)
            if merge_path.exists():
                existing = _load_graph(merge_path)
                if existing is not None:
                    from cortex.portable_runtime import merge_graphs

                    result = merge_graphs(existing, upgrade_v4_to_v5(result)).export_v4()
            else:
                _echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)
        stats = _graph_category_stats(upgrade_v4_to_v5(result))
    claim_count = 0
    if not args.no_claims:
        result, claim_count = _finalize_extraction_output(
            result,
            input_path=input_path,
            fmt=fmt,
            store_dir=Path(args.store_dir),
            record_claims=True,
            extra_metadata=(
                {
                    "detected_sources": [
                        {
                            "target": item["target"],
                            "kind": item["kind"],
                            "path": item["path"],
                        }
                        for item in (detected_payload["selected_sources"] if detected_payload else [])
                    ],
                    "include_config_metadata": bool(getattr(args, "include_config_metadata", False)),
                }
                if detected_payload is not None
                else None
            ),
        )
    v5_output = _to_context_json_v5(result)
    payload = {
        "status": "ok",
        "input_file": str(input_path),
        "output_file": str(
            Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
        ),
        "input_format": fmt,
        "schema_version": v5_output["schema_version"],
        "stats": stats,
        "claim_count": claim_count,
    }
    if detected_payload is not None:
        payload["selected_sources"] = detected_payload["selected_sources"]
        payload["skipped_sources"] = detected_payload["skipped_sources"]
        payload["detected_source_count"] = len(detected_payload["detected_sources"])
    json_only = bool(getattr(args, "json_output", False))
    if not json_only:
        _echo(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if (args.stats or args.verbose) and not json_only:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            _echo(f"   {cat}: {count}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(v5_output, f, indent=2)
    except PermissionError:
        return _permission_error(output_path, action="write context.json")
    except OSError as exc:
        return _error(f"Could not write {output_path}: {exc}")
    if json_only:
        _echo(json.dumps(payload, indent=2), force=True)
    else:
        _echo(f"Saved to: {output_path}")
        if not args.no_claims:
            _echo(f"Recorded {claim_count} claim event(s) to {Path(args.store_dir) / 'claims.jsonl'}")
    return 0


def run_ingest(args):
    """Normalize connector input and extract it into Cortex memory."""
    from cortex.connectors import connector_to_text

    input_path = Path(args.input_file)
    if not input_path.exists():
        return _missing_path_error(input_path, label="Connector input")

    _echo(f"Loading connector input: {input_path}")
    try:
        normalized_text = connector_to_text(args.kind, input_path)
    except PermissionError:
        return _permission_error(input_path, action="read connector input")
    except Exception as exc:
        return _error(str(exc))

    if args.preview:
        _echo(normalized_text.rstrip("\n"))
        return 0

    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                return _missing_path_error(pp, label="Redaction patterns file")
            with open(pp, "r", encoding="utf-8") as f:
                custom_patterns = json.load(f)
        redactor = PIIRedactor(custom_patterns)
        _echo("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            _echo(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            _echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)

    result = extractor.process_plain_text(normalized_text)
    claim_count = 0
    if not args.no_claims:
        result, claim_count = _finalize_extraction_output(
            result,
            input_path=input_path,
            fmt=f"connector:{args.kind}",
            store_dir=Path(args.store_dir),
            record_claims=True,
        )

    stats = extractor.context.stats()
    _echo(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(_to_context_json_v5(result), f, indent=2)
    except PermissionError:
        return _permission_error(output_path, action="write context.json")
    except OSError as exc:
        return _error(f"Could not write {output_path}: {exc}")
    _echo(f"Saved to: {output_path}")
    if not args.no_claims:
        _echo(f"Recorded {claim_count} claim event(s) to {Path(args.store_dir) / 'claims.jsonl'}")
    return 0


def run_import(args):
    """Import a context JSON file and export to platform formats."""
    NormalizedContext = _normalized_context_cls()
    confidence_thresholds = _confidence_thresholds()

    input_path = Path(args.input_file)
    if not input_path.exists():
        return _missing_path_error(input_path, label="Context file")

    _echo(f"Loading: {input_path}")
    ctx = NormalizedContext.load(input_path)
    min_conf = confidence_thresholds[args.confidence]
    format_keys = PLATFORM_FORMATS[args.to]
    output_dir = Path(args.output)

    if args.dry_run:
        _echo("\nDRY RUN PREVIEW")
        export_dispatch = _export_dispatch()
        for key in format_keys:
            export_fn, filename, is_json = export_dispatch[key]
            result = export_fn(ctx, min_conf)
            _echo(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                _echo(line)
        return 0

    try:
        outputs = _write_exports(ctx, min_conf, format_keys, output_dir, args.verbose)
    except PermissionError:
        return _permission_error(output_dir, action="write exported files")
    except OSError as exc:
        return _error(f"Could not write export files into {output_dir}: {exc}")

    _echo(f"\nExported {len(outputs)} files to {output_dir}/:")
    for key, path in outputs:
        _echo(f"   {key}: {path.name}")
    return 0


def run_migrate(args):
    """Full pipeline: extract from export file, then import to platform formats."""
    NormalizedContext = _normalized_context_cls()
    confidence_thresholds = _confidence_thresholds()

    input_path = Path(args.input_file)
    if not input_path.exists():
        return _missing_path_error(input_path, label="Input file")

    # --- Extract phase ---
    _echo(f"Loading: {input_path}")
    try:
        data, detected_format = load_file(input_path)
    except PermissionError:
        return _permission_error(input_path, action="read the input file")
    except Exception as exc:
        return _error(str(exc))

    fmt = args.input_format if args.input_format != "auto" else detected_format
    _echo(f"Format: {fmt}")

    # PII redactor
    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                return _missing_path_error(pp, label="Redaction patterns file")
            with open(pp, "r", encoding="utf-8") as f:
                custom_patterns = json.load(f)
        redactor = PIIRedactor(custom_patterns)
        _echo("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    # Merge
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            _echo(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            _echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)

    v4_data = _run_extraction(extractor, data, fmt)
    claim_count = 0
    if not args.no_claims and not args.dry_run:
        v4_data, claim_count = _finalize_extraction_output(
            v4_data,
            input_path=input_path,
            fmt=fmt,
            store_dir=Path(args.store_dir),
            record_claims=True,
        )

    stats = extractor.context.stats()
    _echo(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            _echo(f"   {cat}: {count}")

    # --- Save intermediate context.json ---
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.schema == "v5":
        graph = upgrade_v4_to_v5(v4_data)

        # --- Smart edge discovery (Phase 4, opt-in) ---
        if getattr(args, "discover_edges", False):
            from cortex.centrality import apply_centrality_boost, compute_centrality
            from cortex.cooccurrence import discover_edges as discover_cooccurrence
            from cortex.dedup import deduplicate
            from cortex.edge_extraction import discover_all_edges

            messages = getattr(extractor, "all_user_text", None)

            # 1. Pattern-based + proximity edge extraction
            new_edges = discover_all_edges(graph, messages=messages)
            for edge in new_edges:
                graph.add_edge(edge)

            # 2. Co-occurrence edges (if messages available)
            cooc_count = 0
            if messages and len(messages) >= 3:
                cooc_edges = discover_cooccurrence(messages, graph)
                for edge in cooc_edges:
                    graph.add_edge(edge)
                cooc_count = len(cooc_edges)

            # 3. Graph-aware dedup
            merged = deduplicate(graph)

            # 4. Centrality boost
            scores = compute_centrality(graph)
            apply_centrality_boost(graph, scores)

            if args.verbose:
                print(
                    f"   Smart edges: +{len(new_edges)} pattern"
                    f", +{cooc_count} co-occurrence"
                    f", {len(merged)} merges, centrality applied"
                )

            if getattr(args, "llm", False):
                print("   --llm: LLM-assisted extraction not yet implemented (stub)")

        v5_data = graph.export_v5()
        ctx_path = output_dir / "context.json"
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(v5_data, f, indent=2)
        if args.verbose:
            gs = graph.stats()
            _echo(f"   v5 graph: {gs['node_count']} nodes, {gs['edge_count']} edges")
            _echo(f"   saved v5 context: {ctx_path}")
    else:
        _echo("Warning: --schema v4 is deprecated. Prefer the default v5 context.json.", stderr=True, force=True)
        ctx_path = output_dir / "context.json"
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(v4_data, f, indent=2)
        if args.verbose:
            _echo(f"   saved intermediate context: {ctx_path}")

    # --- Import phase (in-memory handoff) ---
    ctx = NormalizedContext.from_v4(v4_data)
    min_conf = confidence_thresholds[args.confidence]
    format_keys = PLATFORM_FORMATS[args.to]

    if args.dry_run:
        _echo("\nDRY RUN PREVIEW")
        export_dispatch = _export_dispatch()
        for key in format_keys:
            export_fn, filename, is_json = export_dispatch[key]
            result = export_fn(ctx, min_conf)
            _echo(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                _echo(line)
        return 0

    try:
        outputs = _write_exports(ctx, min_conf, format_keys, output_dir, args.verbose)
    except PermissionError:
        return _permission_error(output_dir, action="write exported files")
    except OSError as exc:
        return _error(f"Could not write export files into {output_dir}: {exc}")

    _echo(f"\nExported {len(outputs) + 1} files to {output_dir}/:")
    _echo("   context: context.json")
    for key, path in outputs:
        _echo(f"   {key}: {path.name}")
    if not args.no_claims and not args.dry_run:
        _echo(f"   claims: {claim_count} event(s) -> {Path(args.store_dir) / 'claims.jsonl'}")
    return 0


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
    print("Specify a memory subcommand: conflicts, show, forget, retract, set, resolve")
    return 1


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
    print("Specify a claim subcommand: log, show, accept, reject, supersede")
    return 1


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


def run_init(args):
    return cli_workspace_commands_module.run_init(args, ctx=_workspace_cli_context())


def run_help_topic(args):
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


def run_connect_manus(args):
    return cli_runtime_commands_module.run_connect_manus(args, ctx=_runtime_cli_context())


def run_connect_runtime_target(args, *, target: str):
    return cli_runtime_commands_module.run_connect_runtime_target(args, target=target, ctx=_runtime_cli_context())


def run_connect(args):
    if args.connect_subcommand == "manus":
        return run_connect_manus(args)
    if args.connect_subcommand in CONNECT_RUNTIME_TARGETS:
        return run_connect_runtime_target(args, target=args.connect_subcommand)
    return _error("Specify a connect target: manus, hermes, codex, cursor, or claude-code")


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
    return _error("Specify a serve target: api, mcp, manus, ui")


def run_ui(args):
    return cli_runtime_commands_module.run_ui(args, ctx=_runtime_cli_context())


def run_server(args):
    return cli_runtime_commands_module.run_server(args, ctx=_runtime_cli_context())


def run_mcp(args):
    return cli_runtime_commands_module.run_mcp(args, ctx=_runtime_cli_context())


def run_openapi(args):
    """Write the OpenAPI contract to disk."""
    from cortex.openapi import write_openapi_spec

    output_path = write_openapi_spec(args.output, server_url=args.server_url, compat_output_path=args.compat_output)
    print(f"Wrote OpenAPI spec to {output_path}")
    if args.compat_output:
        print(f"Wrote OpenAPI compatibility snapshot to {args.compat_output}")
    return 0


def run_release_notes(args):
    """Write Markdown release notes and a JSON release manifest."""
    from cortex.openapi import build_openapi_spec
    from cortex.release import write_release_manifest, write_release_notes

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
    print("Specify a backup subcommand: export, verify, restore, import")
    return 1


def run_stats(args):
    return cli_misc_commands_module.run_stats(args, ctx=_misc_cli_context())


def run_pull(args):
    return cli_misc_commands_module.run_pull(args, ctx=_misc_cli_context())


def run_rotate(args):
    return cli_misc_commands_module.run_rotate(args, ctx=_misc_cli_context())


def run_completion(args):
    return cli_misc_commands_module.run_completion(args, ctx=_misc_cli_context())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv=None):
    return cli_entrypoint_module.main(argv, ctx=_entrypoint_cli_context())


if __name__ == "__main__":
    sys.exit(main())
