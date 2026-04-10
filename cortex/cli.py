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
from typing import TYPE_CHECKING, Any

from cortex import cli_parser as cli_parser_module
from cortex import cli_portable_commands as cli_portable_commands_module
from cortex import cli_runtime_commands as cli_runtime_commands_module
from cortex import cli_surface as cli_surface_module
from cortex import cli_workspace_commands as cli_workspace_commands_module
from cortex.adapters import ADAPTERS
from cortex.compat import upgrade_v4_to_v5
from cortex.contradictions import ContradictionEngine
from cortex.extract_memory import (
    AggressiveExtractor,
    PIIRedactor,
    build_eval_compat_view,
    load_file,
    merge_contexts,
)
from cortex.graph import CortexGraph, Node

if TYPE_CHECKING:
    from cortex.claims import ClaimEvent
    from cortex.schemas.memory_v1 import GovernanceRuleRecord
    from cortex.upai.identity import UPAIIdentity

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


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

build_parser = cli_parser_module.build_parser


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


def run_query(args):
    """Query nodes/neighbors in a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        return _missing_path_error(input_path, label="Context file")

    graph = _load_graph(input_path)
    if args.at:
        graph = graph.graph_at(args.at)

    def _node_payload(node: Node) -> dict[str, object]:
        return node.to_dict()

    # --- Phase 1 queries (--node, --neighbors) ---
    if args.node:
        nodes = graph.find_nodes(label=args.node)
        payload = {
            "status": "ok",
            "query": "node",
            "label": args.node,
            "at": args.at or "",
            "nodes": [_node_payload(node) for node in nodes],
        }
        if _emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            _echo(f"No node found with label '{args.node}'")
            return 0
        for node in nodes:
            _echo(f"Node: {node.label} (id={node.id})")
            _echo(f"  Tags: {', '.join(node.tags)}")
            _echo(f"  Confidence: {node.confidence:.2f}")
            _echo(f"  Mentions: {node.mention_count}")
            if getattr(node, "status", ""):
                _echo(f"  Status: {node.status}")
            if getattr(node, "valid_from", "") or getattr(node, "valid_to", ""):
                _echo(f"  Valid: {getattr(node, 'valid_from', '') or '?'} -> {getattr(node, 'valid_to', '') or '?'}")
            if node.brief:
                _echo(f"  Brief: {node.brief}")
            if node.full_description:
                _echo(f"  Description: {node.full_description}")
        return 0

    if args.neighbors:
        nodes = graph.find_nodes(label=args.neighbors)
        payload = {
            "status": "ok",
            "query": "neighbors",
            "label": args.neighbors,
            "neighbors": [],
        }
        if nodes:
            node = nodes[0]
            payload["neighbors"] = [
                {"edge": edge.to_dict(), "node": neighbor.to_dict()} for edge, neighbor in graph.get_neighbors(node.id)
            ]
        if _emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            _echo(f"No node found with label '{args.neighbors}'")
            return 0
        node = nodes[0]
        neighbors = graph.get_neighbors(node.id)
        if not neighbors:
            _echo(f"No neighbors for '{node.label}'")
            return 0
        _echo(f"Neighbors of '{node.label}':")
        for edge, neighbor in neighbors:
            _echo(f"  --[{edge.relation}]--> {neighbor.label} (conf={neighbor.confidence:.2f})")
        return 0

    # --- Phase 5 queries (QueryEngine) ---
    from cortex.intelligence import GapAnalyzer
    from cortex.query import (
        QueryEngine,
        connected_components,
        parse_nl_query,
    )
    from cortex.query_lang import execute_query

    engine = QueryEngine(graph)

    if args.category:
        nodes = engine.query_category(args.category)
        payload = {
            "status": "ok",
            "query": "category",
            "tag": args.category,
            "nodes": [_node_payload(node) for node in nodes],
        }
        if _emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            _echo(f"No nodes with tag '{args.category}'")
            return 0
        _echo(f"Nodes tagged '{args.category}' ({len(nodes)}):")
        for node in nodes:
            _echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.path:
        from_label, to_label = args.path
        paths = engine.query_path(from_label, to_label)
        payload = {
            "status": "ok",
            "query": "path",
            "from": from_label,
            "to": to_label,
            "paths": [[_node_payload(node) for node in path] for path in paths],
        }
        if _emit_result(payload, args.format) == 0:
            return 0
        if not paths:
            _echo(f"No path from '{from_label}' to '{to_label}'")
            return 0
        _echo(f"Path from '{from_label}' to '{to_label}':")
        for node in paths[0]:
            _echo(f"  -> {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.changed_since:
        result = engine.query_changed(args.changed_since)
        if _emit_result(result, args.format) == 0:
            return 0
        _echo(f"Changes since {result['since']}: {result['total_changed']} total")
        if result["new_nodes"]:
            _echo(f"\nNew ({len(result['new_nodes'])}):")
            for n in result["new_nodes"]:
                _echo(f"  + {n['label']} (conf={n['confidence']:.2f})")
        if result["updated_nodes"]:
            _echo(f"\nUpdated ({len(result['updated_nodes'])}):")
            for n in result["updated_nodes"]:
                _echo(f"  ~ {n['label']} (conf={n['confidence']:.2f})")
        return 0

    if args.strongest:
        nodes = engine.query_strongest(args.strongest)
        payload = {"status": "ok", "query": "strongest", "nodes": [_node_payload(node) for node in nodes]}
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Top {len(nodes)} by confidence:")
        for node in nodes:
            _echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.weakest:
        nodes = engine.query_weakest(args.weakest)
        payload = {"status": "ok", "query": "weakest", "nodes": [_node_payload(node) for node in nodes]}
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Bottom {len(nodes)} by confidence:")
        for node in nodes:
            _echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.isolated:
        analyzer = GapAnalyzer()
        isolated = analyzer.isolated_nodes(graph)
        payload = {"status": "ok", "query": "isolated", "nodes": [_node_payload(node) for node in isolated]}
        if _emit_result(payload, args.format) == 0:
            return 0
        if not isolated:
            _echo("No isolated nodes.")
            return 0
        _echo(f"Isolated nodes ({len(isolated)}):")
        for node in isolated:
            _echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.related is not None:
        if not args.related:
            return _error("Specify a label for --related.", hint="Usage: cortex query <file> --related <LABEL>")
        nodes = engine.query_related(args.related, depth=args.related_depth)
        payload = {
            "status": "ok",
            "query": "related",
            "label": args.related,
            "depth": args.related_depth,
            "nodes": [_node_payload(node) for node in nodes],
        }
        if _emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            _echo(f"No related nodes for '{args.related}'")
            return 0
        _echo(f"Related to '{args.related}' (depth={args.related_depth}):")
        for node in nodes:
            _echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.components:
        comps = connected_components(graph)
        payload = {
            "status": "ok",
            "query": "components",
            "components": [
                {
                    "size": len(comp),
                    "labels": sorted(graph.get_node(nid).label for nid in comp if graph.get_node(nid)),
                }
                for comp in comps
            ],
        }
        if _emit_result(payload, args.format) == 0:
            return 0
        if not comps:
            _echo("No components (empty graph).")
            return 0
        _echo(f"Connected components ({len(comps)}):")
        for i, comp in enumerate(comps, 1):
            labels = sorted(graph.get_node(nid).label for nid in comp if graph.get_node(nid))
            _echo(f"  {i}. [{len(comp)} nodes] {', '.join(labels[:10])}{'...' if len(labels) > 10 else ''}")
        return 0

    if args.search:
        results = graph.semantic_search(args.search, limit=args.limit)
        payload = {
            "status": "ok",
            "query": "search",
            "search": args.search,
            "results": [{"score": item["score"], "node": item["node"].to_dict()} for item in results],
        }
        if _emit_result(payload, args.format) == 0:
            return 0
        if not results:
            _echo(f"No search results for '{args.search}'")
            return 0
        _echo(f"Search results for '{args.search}' ({len(results)}):")
        for item in results:
            node = item["node"]
            aliases = f" | aliases: {', '.join(node.aliases)}" if getattr(node, "aliases", []) else ""
            _echo(f"  {node.label} (score={item['score']:.4f}, conf={node.confidence:.2f}){aliases}")
        return 0

    if args.dsl:
        result = execute_query(graph, args.dsl)
        if result.get("type") == "search" and args.limit and len(result.get("results", [])) > args.limit:
            result["results"] = result["results"][: args.limit]
            result["count"] = len(result["results"])
        if _emit_result(result, args.format) == 0:
            return 0
        _echo(json.dumps(result, indent=2, default=str))
        return 0

    if args.nl:
        result = parse_nl_query(args.nl, engine)
        if _emit_result(result, args.format) == 0:
            return 0
        _echo(json.dumps(result, indent=2, default=str))
        return 0

    return _error(
        "No query option provided.",
        hint=(
            "Specify one of --node, --neighbors, --category, --path, --changed-since, "
            "--strongest, --weakest, --isolated, --related, --components, --search, --dsl, or --nl."
        ),
    )


def _load_graph(input_path: Path) -> CortexGraph:
    """Load a v4, v5, or v6 JSON file and return a CortexGraph."""
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {input_path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except OSError as exc:
        print(f"Error: cannot read {input_path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    version = data.get("schema_version", "")
    if version.startswith("5") or version.startswith("6"):
        return CortexGraph.from_v5_json(data)
    return upgrade_v4_to_v5(data)


def _save_graph(graph: CortexGraph, output_path: Path) -> None:
    output_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def _parse_properties(items: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            print(f"Invalid property: {item!r} (expected key=value)", file=sys.stderr)
            raise SystemExit(1)
        key, value = item.split("=", 1)
        result[key] = value
    return result


def _load_identity(store_dir: Path) -> "UPAIIdentity | None":
    from cortex.upai.identity import UPAIIdentity

    id_path = store_dir / "identity.json"
    if id_path.exists():
        return UPAIIdentity.load(store_dir)
    return None


def _current_branch_or_ref(store, ref: str | None = None) -> str:
    if not ref or ref == "HEAD":
        return store.current_branch()
    return ref


def _governance_decision_or_error(
    *,
    store_dir: Path,
    actor: str,
    action: str,
    namespace: str,
    current_graph: CortexGraph | None = None,
    baseline_graph: CortexGraph | None = None,
    approve: bool = False,
) -> object | None:
    from cortex.storage import get_storage_backend

    governance = get_storage_backend(store_dir).governance
    decision = governance.authorize(
        actor,
        action,
        namespace,
        current_graph=current_graph,
        baseline_graph=baseline_graph,
    )
    if not decision.allowed:
        print(f"Access denied: actor '{actor}' cannot {action} namespace '{namespace}'.")
        for reason in decision.reasons:
            print(f"  - {reason}")
        return None
    if decision.require_approval and not approve:
        print(f"Approval required: actor '{actor}' cannot {action} namespace '{namespace}' without review.")
        for reason in decision.reasons:
            print(f"  - {reason}")
        print("Re-run with --approve after human review.")
        return None
    return decision


def _maybe_commit_graph(graph: CortexGraph, store_dir: Path, message: str | None) -> str | None:
    from cortex.storage import get_storage_backend

    if not message:
        return None
    store = get_storage_backend(store_dir).versions
    identity = _load_identity(store_dir)
    version = store.commit(graph, message, source="manual", identity=identity)
    return version.version_id


def _claim_event_from_record(record: object | None) -> "ClaimEvent | None":
    from cortex.claims import ClaimEvent

    if record is None:
        return None
    if isinstance(record, ClaimEvent):
        return record
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    return ClaimEvent.from_dict(payload)


def _emit_result(result, output_format: str) -> int:
    if output_format == "json":
        _echo(json.dumps(result, indent=2), force=True)
        return 0
    if _CLI_QUIET:
        return 0
    return -1


def run_timeline(args):
    """Generate a timeline from a context/graph file."""
    from cortex.timeline import TimelineGenerator

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    gen = TimelineGenerator()
    events = gen.generate(graph, from_date=args.from_date, to_date=args.to_date)

    if args.output_format == "html":
        print(gen.to_html(events))
    else:
        print(gen.to_markdown(events))
    return 0


def run_memory_conflicts(args):
    from cortex.memory_ops import list_memory_conflicts

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    conflicts = [item.to_dict() for item in list_memory_conflicts(graph, min_severity=args.severity)]
    if _emit_result({"conflicts": conflicts}, args.format) == 0:
        return 0
    if not conflicts:
        print("No memory conflicts.")
        return 0
    print(f"Found {len(conflicts)} memory conflict(s):")
    for conflict in conflicts:
        print(f"  {conflict['id']} [{conflict['type']}] severity={conflict['severity']:.2f}")
        print(f"    {conflict['summary']}")
    return 0


def run_memory_show(args):
    from cortex.memory_ops import show_memory_nodes

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    nodes = show_memory_nodes(graph, label=args.label, tag=args.tag, limit=args.limit)
    if _emit_result({"nodes": nodes}, args.format) == 0:
        return 0
    if not nodes:
        print("No matching memory nodes.")
        return 0
    for node in nodes:
        print(f"{node['label']} ({node['id']})")
        print(f"  Tags: {', '.join(node['tags'])}")
        print(f"  Confidence: {node['confidence']:.2f}")
        if node.get("brief"):
            print(f"  Brief: {node['brief']}")
    return 0


def run_memory_forget(args):
    from cortex.memory_ops import forget_nodes

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    result = forget_nodes(graph, node_id=args.node_id, label=args.label, tag=args.tag, dry_run=args.dry_run)
    if not args.dry_run:
        _save_graph(graph, input_path)
        commit_id = _maybe_commit_graph(graph, Path(args.store_dir), args.commit_message)
        if commit_id:
            result["commit_id"] = commit_id
    if _emit_result(result, args.format) == 0:
        return 0
    print(f"Removed {result['nodes_removed']} node(s).")
    return 0


def run_memory_set(args):
    from cortex.claims import ClaimEvent
    from cortex.memory_ops import set_memory_node
    from cortex.storage import get_storage_backend

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    result = set_memory_node(
        graph,
        label=args.label,
        tags=args.tag,
        aliases=args.alias,
        brief=args.brief,
        description=args.description,
        properties=_parse_properties(args.property),
        confidence=args.confidence,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        status=args.status,
        provenance_source=args.source,
        replace_label=args.replace_label,
    )
    _save_graph(graph, input_path)
    commit_id = _maybe_commit_graph(graph, Path(args.store_dir), args.commit_message)
    if commit_id:
        result["commit_id"] = commit_id
    node = graph.get_node(result["node_id"])
    if node is not None:
        event = ClaimEvent.from_node(
            node,
            op="assert",
            source=args.source or "manual",
            method="manual_set",
            version_id=commit_id or "",
            message=args.commit_message or "",
            metadata={"created": result["created"], "updated": result["updated"]},
        )
        get_storage_backend(Path(args.store_dir)).claims.append(event)
        result["claim_id"] = event.claim_id
        result["claim_event_id"] = event.event_id
    if _emit_result(result, args.format) == 0:
        return 0
    print(f"{'Created' if result['created'] else 'Updated'} node {result['node_id']}.")
    return 0


def run_memory_retract(args):
    from cortex.claims import ClaimEvent
    from cortex.memory_ops import retract_source
    from cortex.storage import get_storage_backend

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    pre_nodes = {node_id: node.to_dict() for node_id, node in graph.nodes.items()}
    result = retract_source(
        graph,
        source=args.source,
        dry_run=args.dry_run,
        prune_orphans=not args.keep_orphans,
    )
    if not args.dry_run:
        _save_graph(graph, input_path)
        commit_id = _maybe_commit_graph(graph, Path(args.store_dir), args.commit_message)
        if commit_id:
            result["commit_id"] = commit_id
        claim_events: list[str] = []
        claim_ids: list[str] = []
        ledger = get_storage_backend(Path(args.store_dir)).claims
        for node_id in result["node_ids"]:
            snapshot = pre_nodes.get(node_id)
            if snapshot is None:
                continue
            event = ClaimEvent.from_node(
                Node.from_dict(snapshot),
                op="retract",
                source=args.source,
                method="memory_retract",
                version_id=commit_id or "",
                message=args.commit_message or "",
                metadata={"removed": node_id not in graph.nodes, "prune_orphans": not args.keep_orphans},
            )
            ledger.append(event)
            claim_events.append(event.event_id)
            claim_ids.append(event.claim_id)
        if claim_events:
            result["claim_event_ids"] = claim_events
            result["claim_ids"] = claim_ids
    if _emit_result(result, args.format) == 0:
        return 0
    print(
        f"Retracted source {result['source']}: "
        f"{result['nodes_touched']} node(s), {result['edges_touched']} edge(s), "
        f"{result['snapshots_removed']} snapshot(s), "
        f"{result['node_provenance_removed'] + result['edge_provenance_removed']} provenance entr{'y' if result['node_provenance_removed'] + result['edge_provenance_removed'] == 1 else 'ies'} removed."
    )
    if result["nodes_removed"] or result["edges_removed"]:
        print(f"Pruned {result['nodes_removed']} node(s) and {result['edges_removed']} edge(s).")
    return 0


def run_blame(args):
    from cortex.memory_ops import blame_memory_nodes
    from cortex.storage import get_storage_backend

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)

    store_path = Path(args.store_dir)
    backend = get_storage_backend(store_path)
    store = backend.versions
    if (
        _governance_decision_or_error(
            store_dir=store_path,
            actor=args.actor,
            action="read",
            namespace=_current_branch_or_ref(store, args.ref),
        )
        is None
    ):
        return 1
    result = blame_memory_nodes(
        graph,
        label=args.label,
        node_id=args.node_id,
        store=backend.versions,
        ledger=backend.claims,
        ref=args.ref,
        source=args.source or "",
        version_limit=args.limit,
    )
    if _emit_result(result, args.format) == 0:
        return 0
    if not result["nodes"]:
        target = args.label or args.node_id or "target"
        print(f"No memory nodes found for '{target}'.")
        return 0

    for item in result["nodes"]:
        node = item["node"]
        print(f"Blame: {node['label']} ({node['id']})")
        print(f"  Tags: {', '.join(node['tags']) if node['tags'] else 'none'}")
        print(f"  Confidence: {node['confidence']:.2f}")
        if node.get("aliases"):
            print(f"  Aliases: {', '.join(node['aliases'])}")
        if node.get("status") or node.get("valid_from") or node.get("valid_to"):
            print(
                f"  Lifecycle: {node.get('status') or 'unspecified'} | {node.get('valid_from') or '?'} -> {node.get('valid_to') or '?'}"
            )
        if item["provenance_sources"]:
            print(f"  Provenance sources: {', '.join(item['provenance_sources'])}")
        if item["snapshot_sources"]:
            print(f"  Snapshot sources: {', '.join(item['snapshot_sources'])}")
        if item["why_present"]:
            print("  Why present:")
            for reason in item["why_present"]:
                print(f"    - {reason}")
        if node.get("source_quotes"):
            print("  Source quotes:")
            for quote in node["source_quotes"][:3]:
                print(f"    - {quote}")

        history = item.get("history")
        if history and history.get("versions_seen"):
            introduced = history.get("introduced_in")
            last_seen = history.get("last_seen_in")
            print("  Version history:")
            if introduced:
                print(
                    f"    Introduced: {introduced['version_id'][:8]} {introduced['timestamp']} "
                    f"[{introduced['source']}] {introduced['message']}"
                )
            if last_seen:
                print(
                    f"    Last seen:  {last_seen['version_id'][:8]} {last_seen['timestamp']} "
                    f"[{last_seen['source']}] {last_seen['message']}"
                )
            print(
                f"    Seen in {history['versions_seen']} version(s); "
                f"changed in {history['versions_changed']} version(s)."
            )
            print("    Recent history:")
            for entry in history["history"][-5:]:
                marker = "*" if entry["changed"] else "-"
                print(
                    f"      {marker} {entry['version_id'][:8]} {entry['timestamp']} "
                    f"[{entry['source']}] {entry['message']}"
                )
        claim_lineage = item.get("claim_lineage")
        if claim_lineage and claim_lineage.get("event_count"):
            print("  Claim ledger:")
            print(
                f"    {claim_lineage['event_count']} event(s) across {claim_lineage['claim_count']} claim(s); "
                f"{claim_lineage['assert_count']} assert, {claim_lineage['retract_count']} retract."
            )
            if claim_lineage.get("sources"):
                print(f"    Sources: {', '.join(claim_lineage['sources'])}")
            introduced = claim_lineage.get("introduced_at")
            if introduced:
                version = introduced.get("version_id", "")
                version_label = version[:8] if version else "local"
                print(
                    f"    First claim event: {introduced['timestamp']} "
                    f"[{introduced.get('source') or '-'}] {introduced.get('method') or '-'} {version_label}"
                )
            latest_event = claim_lineage.get("latest_event")
            if latest_event:
                version = latest_event.get("version_id", "")
                version_label = version[:8] if version else "local"
                print(
                    f"    Latest claim event: {latest_event['timestamp']} "
                    f"[{latest_event.get('op')}] {latest_event.get('source') or '-'} "
                    f"{latest_event.get('method') or '-'} {version_label}"
                )
            print("    Recent claim events:")
            for event in claim_lineage["events"][:5]:
                version_label = event["version_id"][:8] if event.get("version_id") else "local"
                print(
                    f"      - {event['timestamp']} [{event['op']}] "
                    f"{event.get('source') or '-'} {event.get('method') or '-'} "
                    f"{version_label} claim={event['claim_id']}"
                )
        print()
    return 0


def run_history(args):
    from cortex.memory_ops import blame_memory_nodes
    from cortex.storage import get_storage_backend

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)

    store_path = Path(args.store_dir)
    backend = get_storage_backend(store_path)
    store = backend.versions
    if (
        _governance_decision_or_error(
            store_dir=store_path,
            actor=args.actor,
            action="read",
            namespace=_current_branch_or_ref(store, args.ref),
        )
        is None
    ):
        return 1
    result = blame_memory_nodes(
        graph,
        label=args.label,
        node_id=args.node_id,
        store=backend.versions,
        ledger=backend.claims,
        ref=args.ref,
        source=args.source or "",
        version_limit=args.limit,
    )
    payload = {
        "status": result["status"],
        "ref": args.ref,
        "source": args.source or "",
        "nodes": result["nodes"],
    }
    if _emit_result(payload, args.format) == 0:
        return 0
    if not result["nodes"]:
        target = args.label or args.node_id or "target"
        print(f"No history found for '{target}'.")
        return 0

    for item in result["nodes"]:
        node = item["node"]
        print(f"History: {node['label']} ({node['id']})")
        if args.source:
            print(f"  Source filter: {args.source}")
        print(f"  Ref: {args.ref}")
        history = item.get("history")
        if history and history.get("history"):
            print("  Version timeline:")
            for entry in history["history"]:
                version_node = entry["node"]
                print(f"    {entry['timestamp']} {entry['version_id'][:8]} [{entry['source']}] {entry['message']}")
                print(
                    f"      label={version_node['label']} tags={','.join(version_node['tags']) or '-'} "
                    f"status={version_node.get('status') or '-'} "
                    f"window={version_node.get('valid_from') or '?'}->{version_node.get('valid_to') or '?'}"
                )
        claim_lineage = item.get("claim_lineage")
        if claim_lineage and claim_lineage.get("events"):
            print("  Claim events:")
            for event in reversed(claim_lineage["events"]):
                version_label = event["version_id"][:8] if event.get("version_id") else "local"
                print(
                    f"    {event['timestamp']} [{event['op']}] "
                    f"source={event.get('source') or '-'} method={event.get('method') or '-'} "
                    f"version={version_label} claim={event['claim_id']}"
                )
        print()
    return 0


def _find_claim_target_node(graph: CortexGraph, event: "ClaimEvent") -> Node | None:
    if event.node_id and graph.get_node(event.node_id):
        return graph.get_node(event.node_id)
    if event.canonical_id:
        for node in graph.nodes.values():
            if node.canonical_id == event.canonical_id:
                return node
    matches = graph.find_node_ids_by_label(event.label)
    if matches:
        return graph.get_node(matches[0])
    return None


def _load_claim_or_error(store_dir: Path, claim_id: str) -> tuple[object, "ClaimEvent | None"]:
    from cortex.storage import get_storage_backend

    ledger = get_storage_backend(store_dir).claims
    return ledger, _claim_event_from_record(ledger.latest_event(claim_id))


def run_claim_accept(args):
    from cortex.claims import ClaimEvent, claim_event_to_node

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    ledger, latest = _load_claim_or_error(Path(args.store_dir), args.claim_id)
    if latest is None:
        print(f"No claim events found for {args.claim_id}.")
        return 1

    node = _find_claim_target_node(graph, latest)
    restored = False
    if node is None:
        graph.add_node(claim_event_to_node(latest))
        node = graph.get_node(latest.node_id)
        restored = True
    assert node is not None
    node.label = latest.label
    node.aliases = list(dict.fromkeys(node.aliases + list(latest.aliases)))
    node.tags = list(dict.fromkeys(node.tags + list(latest.tags)))
    node.confidence = max(node.confidence, latest.confidence)
    if latest.status:
        node.status = latest.status
    if latest.valid_from:
        node.valid_from = latest.valid_from
    if latest.valid_to:
        node.valid_to = latest.valid_to
    if latest.canonical_id:
        node.canonical_id = latest.canonical_id
    if latest.source:
        provenance_entry = {"source": latest.source, "method": "claim_accept"}
        if provenance_entry not in node.provenance:
            node.provenance.append(provenance_entry)

    _save_graph(graph, input_path)
    commit_id = _maybe_commit_graph(graph, Path(args.store_dir), args.commit_message)
    decision = ClaimEvent.decision_from_event(
        latest,
        op="accept",
        version_id=commit_id or "",
        message=args.commit_message or "",
        metadata={"restored": restored},
    )
    ledger.append(decision)
    payload = {
        "status": "ok",
        "claim_id": args.claim_id,
        "node_id": node.id,
        "restored": restored,
        "claim_event_id": decision.event_id,
    }
    if commit_id:
        payload["commit_id"] = commit_id
    if _emit_result(payload, args.format) == 0:
        return 0
    print(f"Accepted claim {args.claim_id} for node {node.label}.")
    return 0


def run_claim_reject(args):
    from cortex.claims import ClaimEvent

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    ledger, latest = _load_claim_or_error(Path(args.store_dir), args.claim_id)
    if latest is None:
        print(f"No claim events found for {args.claim_id}.")
        return 1

    node = _find_claim_target_node(graph, latest)
    removed = False
    updated = False
    if node is not None:
        node.tags = [tag for tag in node.tags if tag not in latest.tags]
        if latest.source:
            node.provenance = [item for item in node.provenance if item.get("source") != latest.source]
        if node.status == latest.status:
            node.status = ""
        if node.valid_from == latest.valid_from:
            node.valid_from = ""
        if node.valid_to == latest.valid_to:
            node.valid_to = ""
        if not node.tags and not node.provenance:
            graph.remove_node(node.id)
            removed = True
        else:
            updated = True

    _save_graph(graph, input_path)
    commit_id = _maybe_commit_graph(graph, Path(args.store_dir), args.commit_message)
    decision = ClaimEvent.decision_from_event(
        latest,
        op="reject",
        version_id=commit_id or "",
        message=args.commit_message or "",
        metadata={"removed": removed, "updated": updated},
    )
    ledger.append(decision)
    payload = {
        "status": "ok",
        "claim_id": args.claim_id,
        "node_id": latest.node_id,
        "removed": removed,
        "updated": updated,
        "claim_event_id": decision.event_id,
    }
    if commit_id:
        payload["commit_id"] = commit_id
    if _emit_result(payload, args.format) == 0:
        return 0
    print(f"Rejected claim {args.claim_id}.")
    return 0


def run_claim_supersede(args):
    from cortex.claims import ClaimEvent, claim_event_to_node

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    ledger, latest = _load_claim_or_error(Path(args.store_dir), args.claim_id)
    if latest is None:
        print(f"No claim events found for {args.claim_id}.")
        return 1

    updated_node = claim_event_to_node(latest)
    if args.label:
        updated_node.label = args.label
    if args.tags:
        updated_node.tags = list(dict.fromkeys(args.tags))
    if args.alias:
        updated_node.aliases = list(dict.fromkeys(updated_node.aliases + args.alias))
    if args.status is not None:
        updated_node.status = args.status or ""
    if args.valid_from:
        updated_node.valid_from = args.valid_from
    if args.valid_to:
        updated_node.valid_to = args.valid_to
    if args.confidence is not None:
        updated_node.confidence = args.confidence
    if not any(
        [
            args.label,
            args.tags,
            args.alias,
            args.status is not None,
            args.valid_from,
            args.valid_to,
            args.confidence is not None,
        ]
    ):
        print("Provide at least one override to supersede a claim.")
        return 1

    node = _find_claim_target_node(graph, latest)
    if node is not None:
        graph.nodes[node.id] = updated_node
    else:
        graph.add_node(updated_node)

    _save_graph(graph, input_path)
    commit_id = _maybe_commit_graph(graph, Path(args.store_dir), args.commit_message)
    supersede_event = ClaimEvent.decision_from_event(
        latest,
        op="supersede",
        version_id=commit_id or "",
        message=args.commit_message or "",
        metadata={"superseded_by_label": updated_node.label},
    )
    ledger.append(supersede_event)
    new_assert = ClaimEvent.from_node(
        updated_node,
        op="assert",
        source=latest.source,
        method="claim_supersede",
        version_id=commit_id or "",
        message=args.commit_message or "",
        metadata={"supersedes": args.claim_id},
    )
    ledger.append(new_assert)
    payload = {
        "status": "ok",
        "superseded_claim_id": args.claim_id,
        "new_claim_id": new_assert.claim_id,
        "node_id": updated_node.id,
        "claim_event_ids": [supersede_event.event_id, new_assert.event_id],
    }
    if commit_id:
        payload["commit_id"] = commit_id
    if _emit_result(payload, args.format) == 0:
        return 0
    print(f"Superseded claim {args.claim_id} with {new_assert.claim_id}.")
    return 0


def run_claim_log(args):
    from cortex.storage import get_storage_backend

    ledger = get_storage_backend(Path(args.store_dir)).claims
    events = ledger.list_events(
        label=args.label or "",
        node_id=args.node_id or "",
        source=args.source or "",
        version_ref=args.version or "",
        op=args.op or "",
        limit=args.limit,
    )
    payload = {"events": [event.to_dict() for event in events]}
    if _emit_result(payload, args.format) == 0:
        return 0
    if not events:
        print("No claim events found.")
        return 0
    print(f"Claim events ({len(events)}):")
    for event in events:
        version = event.version_id[:8] if event.version_id else "local"
        print(f"  {event.timestamp} [{event.op}] {event.label} source={event.source or '-'} version={version}")
    return 0


def run_claim_show(args):
    from cortex.storage import get_storage_backend

    ledger = get_storage_backend(Path(args.store_dir)).claims
    events = ledger.get_claim(args.claim_id)
    payload = {"claim_id": args.claim_id, "events": [event.to_dict() for event in events]}
    if _emit_result(payload, args.format) == 0:
        return 0
    if not events:
        print(f"No claim events found for {args.claim_id}.")
        return 0
    first = events[0]
    print(f"Claim {args.claim_id}: {first.label}")
    for event in events:
        version = event.version_id[:8] if event.version_id else "local"
        print(
            f"  {event.timestamp} [{event.op}] source={event.source or '-'} "
            f"method={event.method or '-'} version={version}"
        )
    return 0


def run_memory_resolve(args):
    from cortex.memory_ops import resolve_memory_conflict

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    result = resolve_memory_conflict(graph, args.conflict_id, args.action)
    if result.get("status") == "ok" and args.action != "ignore":
        _save_graph(graph, input_path)
        commit_id = _maybe_commit_graph(graph, Path(args.store_dir), args.commit_message)
        if commit_id:
            result["commit_id"] = commit_id
    if _emit_result(result, args.format) == 0:
        return 0
    if result.get("status") != "ok":
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1
    print(f"Resolved {result['conflict_id']} with action {result['action']}.")
    return 0


def run_contradictions(args):
    """Detect contradictions in a context/graph file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    engine = ContradictionEngine()
    contradictions = engine.detect_all(graph, min_severity=args.severity)

    if args.contradiction_type:
        contradictions = [c for c in contradictions if c.type == args.contradiction_type]

    if args.format == "json":
        print(json.dumps({"contradictions": [c.to_dict() for c in contradictions]}, indent=2))
        return 0

    if not contradictions:
        print("No contradictions detected.")
        return 0

    print(f"Found {len(contradictions)} contradiction(s):\n")
    for c in contradictions:
        print(f"  [{c.type}] severity={c.severity:.2f}")
        print(f"    {c.description}")
        print(f"    Resolution: {c.resolution}")
        print(f"    Nodes: {', '.join(c.node_ids)}")
        print()
    return 0


def run_drift(args):
    """Compute identity drift between two graph files."""
    from cortex.temporal import drift_score

    input_path = Path(args.input_file)
    compare_path = Path(args.compare)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    if not compare_path.exists():
        print(f"File not found: {compare_path}")
        return 1

    graph_a = _load_graph(input_path)
    graph_b = _load_graph(compare_path)
    result = drift_score(graph_a, graph_b)

    if not result["sufficient_data"]:
        print("Insufficient data for drift analysis.")
        print(f"  Graph A: {result['details']['node_count_a']} nodes")
        print(f"  Graph B: {result['details']['node_count_b']} nodes")
        print("  Need at least 3 nodes in each graph.")
        return 0

    print(f"Identity Drift Score: {result['score']:.4f}")
    print(f"  Label drift:      {result['details']['label_drift']:.4f}")
    print(f"  Tag drift:        {result['details']['tag_drift']:.4f}")
    print(f"  Confidence drift: {result['details']['confidence_drift']:.4f}")
    print(f"  Graph A: {result['details']['node_count_a']} nodes")
    print(f"  Graph B: {result['details']['node_count_b']} nodes")
    return 0


def _resolve_version_or_exit(store, version_ref: str) -> str:
    resolved = store.resolve_ref(version_ref)
    if resolved is None:
        print(f"Version not found or ambiguous: {version_ref}")
        raise SystemExit(1)
    return resolved


def _resolve_version_at_or_exit(store, timestamp: str, ref: str | None = None) -> str:
    resolved = store.resolve_at(timestamp, ref=ref)
    if resolved is None:
        scope = f" on {ref}" if ref else ""
        print(f"Version not found at or before {timestamp}{scope}")
        raise SystemExit(1)
    return resolved


def run_diff(args):
    """Compare two stored graph versions."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    if (
        _governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=_current_branch_or_ref(store, args.version_a),
        )
        is None
    ):
        return 1
    if (
        _governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=_current_branch_or_ref(store, args.version_b),
        )
        is None
    ):
        return 1
    version_a = _resolve_version_or_exit(store, args.version_a)
    version_b = _resolve_version_or_exit(store, args.version_b)
    diff = store.diff(version_a, version_b)
    payload = {
        "version_a": version_a,
        "version_b": version_b,
        **diff,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Diff {version_a} -> {version_b}")
    print(f"  Added: {len(diff['added'])}")
    print(f"  Removed: {len(diff['removed'])}")
    print(f"  Modified: {len(diff['modified'])}")
    print(f"  Semantic changes: {diff.get('semantic_summary', {}).get('total', 0)}")
    if diff["added"]:
        print("\nAdded:")
        for node_id in diff["added"]:
            print(f"  + {node_id}")
    if diff["removed"]:
        print("\nRemoved:")
        for node_id in diff["removed"]:
            print(f"  - {node_id}")
    if diff["modified"]:
        print("\nModified:")
        for item in diff["modified"]:
            print(f"  ~ {item['node_id']}: {', '.join(sorted(item['changes'].keys()))}")
    if diff.get("semantic_changes"):
        print("\nSemantic changes:")
        for item in diff["semantic_changes"][:20]:
            print(f"  * {item['type']}: {item['description']}")
    return 0


def run_checkout(args):
    """Write a stored graph version to a file."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    if (
        _governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=_current_branch_or_ref(store, args.version_id),
        )
        is None
    ):
        return 1
    version_id = _resolve_version_or_exit(store, args.version_id)
    graph = store.checkout(version_id, verify=not args.no_verify)
    output_path = Path(args.output) if args.output else Path(f"{version_id}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")
    print(f"Checked out {version_id} to {output_path}")
    return 0


def run_rollback(args):
    """Restore a stored graph state as a new commit without rewriting history."""
    from cortex.storage import get_storage_backend

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    current_branch = store.current_branch()

    if args.target_ref:
        target_version = _resolve_version_or_exit(store, args.target_ref)
        target_label = args.target_ref
    else:
        target_version = _resolve_version_at_or_exit(store, args.target_time, ref=args.ref)
        target_label = args.target_time

    restored = store.checkout(target_version)
    baseline_version = store.resolve_ref("HEAD")
    baseline_graph = store.checkout(baseline_version) if baseline_version else None
    if (
        _governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="rollback",
            namespace=current_branch,
            current_graph=restored,
            baseline_graph=baseline_graph,
            approve=args.approve,
        )
        is None
    ):
        return 1

    _save_graph(restored, input_path)
    identity = _load_identity(store_dir)
    message = args.message or f"Rollback {current_branch} to {target_label}"
    version = store.commit(restored, message, source="rollback", identity=identity)
    payload = {
        "status": "ok",
        "target": target_label,
        "target_version": target_version,
        "rollback_commit": version.version_id,
        "branch": version.namespace,
        "output": str(input_path),
    }
    if _emit_result(payload, args.format) == 0:
        return 0
    print(f"Rolled back {current_branch} to {target_version} as new commit {version.version_id}.")
    print(f"  Wrote restored graph to {input_path}")
    return 0


def run_identity(args):
    """Init or show UPAI identity."""
    from cortex.upai.identity import UPAIIdentity

    store_dir = Path(args.store_dir)

    if args.init:
        name = args.name or "Anonymous"
        identity = UPAIIdentity.generate(name)
        identity.save(store_dir)
        print(f"Identity created: {identity.did}")
        print(f"  Name: {identity.name}")
        print(f"  Created: {identity.created_at}")
        print(f"  Stored in: {store_dir}")
        return 0

    if args.show:
        id_path = store_dir / "identity.json"
        if not id_path.exists():
            print(f"No identity found in {store_dir}. Use --init to create one.")
            return 1
        identity = UPAIIdentity.load(store_dir)
        print(f"DID: {identity.did}")
        print(f"Name: {identity.name}")
        print(f"Created: {identity.created_at}")
        print(f"Public Key: {identity.public_key_b64[:32]}...")
        return 0

    if getattr(args, "did_doc", False):
        id_path = store_dir / "identity.json"
        if not id_path.exists():
            print(f"No identity found in {store_dir}. Use --init to create one.")
            return 1
        identity = UPAIIdentity.load(store_dir)
        doc = identity.to_did_document()
        print(json.dumps(doc, indent=2))
        return 0

    if getattr(args, "keychain", False):
        from cortex.upai.keychain import Keychain

        id_path = store_dir / "identity.json"
        if not id_path.exists():
            print(f"No identity found in {store_dir}. Use --init to create one.")
            return 1
        kc = Keychain(store_dir)
        history = kc.get_history()
        if not history:
            print("No key history found.")
            return 0
        errors = kc.verify_rotation_chain()
        chain_status = "VALID" if not errors else "INVALID"
        print(f"Key Rotation History (chain: {chain_status}):")
        for record in history:
            if record.revoked_at:
                status = f"REVOKED ({record.revocation_reason})"
                date_info = f"created={record.created_at}, revoked={record.revoked_at}"
            else:
                status = "ACTIVE"
                date_info = f"created={record.created_at}"
            print(f"  {record.did[:32]}... | {status} | {date_info}")
        if errors:
            print("\nChain errors:")
            for err in errors:
                print(f"  - {err}")
        return 0

    print("Specify --init, --show, --did-doc, or --keychain")
    return 1


def run_commit(args):
    """Version a graph snapshot."""
    from cortex.storage import get_storage_backend
    from cortex.upai.identity import UPAIIdentity

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    store_dir = Path(args.store_dir)

    # Load identity if available
    identity = None
    id_path = store_dir / "identity.json"
    if id_path.exists():
        identity = UPAIIdentity.load(store_dir)

    store = get_storage_backend(store_dir).versions
    baseline_version = store.resolve_ref("HEAD")
    baseline_graph = store.checkout(baseline_version) if baseline_version else None
    if (
        _governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="write",
            namespace=store.current_branch(),
            current_graph=graph,
            baseline_graph=baseline_graph,
            approve=args.approve,
        )
        is None
    ):
        return 1
    version = store.commit(graph, args.message, source=args.source, identity=identity)

    print(f"Committed: {version.version_id}")
    print(f"  Branch: {version.namespace}")
    print(f"  Message: {version.message}")
    print(f"  Source: {version.source}")
    print(f"  Nodes: {version.node_count}, Edges: {version.edge_count}")
    if version.parent_id:
        print(f"  Parent: {version.parent_id}")
    if version.signature:
        print("  Signed: yes")
    return 0


def run_branch(args):
    """List or create memory branches."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions

    if args.branch_name:
        if (
            _governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="branch",
                namespace=args.branch_name,
            )
            is None
        ):
            return 1
        try:
            head = store.create_branch(args.branch_name, from_ref=args.from_ref, switch=args.switch)
        except ValueError as exc:
            print(str(exc))
            return 1
        payload = {
            "branch": args.branch_name,
            "head": head,
            "current_branch": store.current_branch(),
            "created": True,
        }
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return 0
        print(f"Created branch {args.branch_name}")
        if head:
            print(f"  From: {head}")
        if args.switch:
            print(f"  Switched to {args.branch_name}")
        return 0

    branches = store.list_branches()
    if args.format == "json":
        print(
            json.dumps(
                {"current_branch": store.current_branch(), "branches": [branch.to_dict() for branch in branches]},
                indent=2,
            )
        )
        return 0

    for branch in branches:
        marker = "*" if branch.current else " "
        head = branch.head[:8] if branch.head else "(empty)"
        print(f"{marker} {branch.name:<24} {head}")
    return 0


def run_switch(args):
    """Switch the active memory branch or run a platform portability migration."""
    if getattr(args, "to_platform", None):
        from cortex.portable_runtime import default_output_dir, switch_portability

        input_path = Path(args.from_ref)
        if not input_path.exists():
            print(f"File not found: {input_path}")
            return 1
        project_dir = Path(args.project) if args.project else Path.cwd()
        output_dir = Path(args.output) if args.output else default_output_dir(Path(args.store_dir))
        payload = switch_portability(
            input_path,
            to_target=args.to_platform,
            store_dir=Path(args.store_dir),
            project_dir=project_dir,
            output_dir=output_dir,
            input_format=args.input_format,
            policy_name=args.policy,
            max_chars=args.max_chars,
            dry_run=args.dry_run,
        )
        print(f"Portable switch ready: {payload['source']} -> {args.to_platform}")
        for result in payload["targets"]:
            joined = ", ".join(result["paths"]) if result["paths"] else "(no files)"
            print(f"  {result['target']}: {joined} [{result['status']}]")
        return 0

    if not args.branch_name:
        print("Specify a branch name, or use --to for platform switch mode.")
        return 1
    from cortex.storage import get_storage_backend

    store = get_storage_backend(Path(args.store_dir)).versions
    try:
        if args.create:
            store.create_branch(args.branch_name, from_ref=args.from_ref, switch=True)
        else:
            store.switch_branch(args.branch_name)
    except ValueError as exc:
        print(str(exc))
        return 1

    head = store.resolve_ref("HEAD")
    print(f"Switched to {store.current_branch()}")
    if head:
        print(f"  Head: {head}")
    return 0


def run_merge(args):
    """Merge another branch/ref into the current branch."""
    from cortex.merge import (
        clear_merge_state,
        load_merge_state,
        load_merge_worktree,
        merge_refs,
        resolve_merge_conflict,
        save_merge_state,
    )
    from cortex.storage import get_storage_backend
    from cortex.upai.identity import UPAIIdentity

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    current_branch = store.current_branch()

    if args.abort:
        state = load_merge_state(store_dir)
        if state is None:
            print("No pending merge state found.")
            return 0
        clear_merge_state(store_dir)
        print(f"Aborted pending merge into {state['current_branch']} from {state['other_ref']}.")
        return 0

    if args.conflicts:
        if (
            _governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="read",
                namespace=current_branch,
            )
            is None
        ):
            return 1
        state = load_merge_state(store_dir)
        if state is None:
            payload = {"status": "ok", "pending": False, "conflicts": []}
            if args.format == "json":
                print(json.dumps(payload, indent=2))
            else:
                print("No pending merge conflicts.")
            return 0
        payload = {
            "status": "ok",
            "pending": True,
            "current_branch": state["current_branch"],
            "other_ref": state["other_ref"],
            "conflicts": state.get("conflicts", []),
        }
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(f"Pending merge into {state['current_branch']} from {state['other_ref']}")
            for conflict in state.get("conflicts", []):
                field = f" [{conflict.get('field')}]" if conflict.get("field") else ""
                print(f"  - {conflict['id']} {conflict['kind']}{field}: {conflict['description']}")
        return 0

    if args.resolve:
        if not args.choose:
            print("Specify --choose current|incoming when resolving a merge conflict.")
            return 1
        try:
            payload = resolve_merge_conflict(store, store_dir, args.resolve, args.choose)
        except ValueError as exc:
            print(str(exc))
            return 1
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Resolved merge conflict {payload['resolved_conflict_id']} with {payload['choice']}; "
                f"{payload['remaining_conflicts']} conflict(s) remain."
            )
        return 0

    if args.commit_resolved:
        baseline_version = store.resolve_ref("HEAD")
        baseline_graph = store.checkout(baseline_version) if baseline_version else None
        state = load_merge_state(store_dir)
        if state is None:
            print("No pending merge state found.")
            return 1
        conflicts = state.get("conflicts", [])
        if conflicts:
            print(f"Cannot commit merge; {len(conflicts)} conflict(s) remain.")
            return 1
        graph = load_merge_worktree(store_dir)
        if (
            _governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="merge",
                namespace=current_branch,
                current_graph=graph,
                baseline_graph=baseline_graph,
                approve=args.approve,
            )
            is None
        ):
            return 1
        identity = UPAIIdentity.load(store_dir) if (store_dir / "identity.json").exists() else None
        message = args.message or f"Merge branch '{state['other_ref']}' into {state['current_branch']}"
        merge_parent_ids = (
            [state["other_version"]]
            if state.get("other_version") and state.get("other_version") != state.get("current_version")
            else []
        )
        version = store.commit(
            graph,
            message,
            source="merge",
            identity=identity,
            parent_id=state.get("current_version"),
            branch=state["current_branch"],
            merge_parent_ids=merge_parent_ids,
        )
        clear_merge_state(store_dir)
        payload = {"status": "ok", "commit_id": version.version_id, "message": message}
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(f"Committed resolved merge: {version.version_id}")
        return 0

    if not args.ref_name:
        print("Specify a branch/ref to merge, or use --conflicts, --resolve, --commit-resolved, or --abort.")
        return 1

    try:
        result = merge_refs(store, "HEAD", args.ref_name)
    except ValueError as exc:
        print(str(exc))
        return 1

    payload = {
        "current_branch": current_branch,
        "merged_ref": args.ref_name,
        "base_version": result.base_version,
        "current_version": result.current_version,
        "other_version": result.other_version,
        "summary": result.summary,
        "conflicts": [conflict.to_dict() for conflict in result.conflicts],
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result.merged.export_v5(), indent=2), encoding="utf-8")
        payload["output"] = str(output_path)

    no_changes = (
        result.summary.get("summary", {}).get("added", 0) == 0
        and result.summary.get("summary", {}).get("removed", 0) == 0
        and result.summary.get("summary", {}).get("modified", 0) == 0
        and result.summary.get("summary", {}).get("edges_added", 0) == 0
        and result.summary.get("summary", {}).get("edges_removed", 0) == 0
    )

    if result.ok and not args.dry_run and not no_changes:
        baseline_version = store.resolve_ref("HEAD")
        baseline_graph = store.checkout(baseline_version) if baseline_version else None
        if (
            _governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="merge",
                namespace=current_branch,
                current_graph=result.merged,
                baseline_graph=baseline_graph,
                approve=args.approve,
            )
            is None
        ):
            return 1
        identity = UPAIIdentity.load(store_dir) if (store_dir / "identity.json").exists() else None
        message = args.message or f"Merge branch '{args.ref_name}' into {current_branch}"
        merge_parent_ids = (
            [result.other_version] if result.other_version and result.other_version != result.current_version else []
        )
        version = store.commit(
            result.merged,
            message,
            source="merge",
            identity=identity,
            parent_id=result.current_version,
            branch=current_branch,
            merge_parent_ids=merge_parent_ids,
        )
        payload["commit_id"] = version.version_id
    elif result.conflicts and not args.dry_run:
        state = save_merge_state(
            store_dir,
            current_branch=current_branch,
            other_ref=args.ref_name,
            result=result,
        )
        payload["pending_merge"] = True
        payload["pending_conflicts"] = len(state["conflicts"])

    if args.format == "json":
        print(json.dumps(payload, indent=2))
        return 0 if result.ok else 1

    if no_changes and result.ok:
        print(f"Already up to date: {current_branch} already contains {args.ref_name}")
        return 0

    print(f"Merging {args.ref_name} into {current_branch}")
    if result.base_version:
        print(f"  Base:    {result.base_version}")
    if result.current_version:
        print(f"  Current: {result.current_version}")
    if result.other_version:
        print(f"  Other:   {result.other_version}")
    print(
        "  Summary:"
        f" +{result.summary.get('summary', {}).get('added', 0)}"
        f" -{result.summary.get('summary', {}).get('removed', 0)}"
        f" ~{result.summary.get('summary', {}).get('modified', 0)}"
    )
    if result.conflicts:
        print("  Conflicts:")
        for conflict in result.conflicts:
            field = f" [{conflict.field}]" if conflict.field else ""
            print(f"    - {conflict.id} {conflict.kind}{field}: {conflict.description}")
        if not args.dry_run:
            print(
                "  Pending merge state saved. Use `cortex merge --conflicts` and `cortex merge --resolve <id> --choose ...`."
            )
        return 1
    if payload.get("commit_id"):
        print(f"  Committed merge: {payload['commit_id']}")
    elif args.dry_run:
        print("  Dry run only, no commit created.")
    return 0


def run_review(args):
    """Review a graph or stored ref against a baseline."""
    from cortex.review import parse_failure_policies, review_graphs
    from cortex.storage import get_storage_backend

    backend = get_storage_backend(Path(args.store_dir))
    store = backend.versions
    against_version = _resolve_version_or_exit(store, args.against)
    against_graph = store.checkout(against_version)
    try:
        fail_policies = parse_failure_policies(args.fail_on)
    except ValueError as exc:
        print(str(exc))
        return 1

    if args.input_file:
        input_path = Path(args.input_file)
        if not input_path.exists():
            print(f"File not found: {input_path}")
            return 1
        current_graph = _load_graph(input_path)
        current_label = str(input_path)
    else:
        current_version = _resolve_version_or_exit(store, args.ref)
        current_graph = store.checkout(current_version)
        current_label = current_version

    review = review_graphs(
        current_graph,
        against_graph,
        current_label=current_label,
        against_label=against_version,
    )
    result = review.to_dict()
    should_fail, failure_counts = review.should_fail(fail_policies)
    result["fail_on"] = fail_policies
    result["failure_counts"] = failure_counts
    result["status"] = "fail" if should_fail else "pass"

    if args.format == "json":
        print(json.dumps(result, indent=2))
    elif args.format == "md":
        print(review.to_markdown(fail_policies), end="")
    else:
        summary = result["summary"]
        print(f"Review {result['current']} against {result['against']}")
        print(
            "  Summary:"
            f" +{summary['added_nodes']}"
            f" -{summary['removed_nodes']}"
            f" ~{summary['modified_nodes']}"
            f" contradictions={summary['new_contradictions']}"
            f" temporal_gaps={summary['new_temporal_gaps']}"
            f" low_confidence={summary['introduced_low_confidence_active_priorities']}"
            f" retractions={summary['new_retractions']}"
            f" semantic={summary['semantic_changes']}"
        )
        print(f"  Gates: {', '.join(fail_policies)} -> {result['status']}")
        if result["diff"]["added_nodes"]:
            print("  Added nodes:")
            for item in result["diff"]["added_nodes"][:10]:
                print(f"    + {item['label']} ({item['id']})")
        if result["diff"]["modified_nodes"]:
            print("  Modified nodes:")
            for item in result["diff"]["modified_nodes"][:10]:
                print(f"    ~ {item['label']}: {', '.join(sorted(item['changes']))}")
        if result["new_contradictions"]:
            print("  New contradictions:")
            for item in result["new_contradictions"][:10]:
                print(f"    - {item['type']}: {item['description']}")
        if result["new_temporal_gaps"]:
            print("  New temporal gaps:")
            for item in result["new_temporal_gaps"][:10]:
                print(f"    - {item['label']}: {item['kind']}")
        if result["semantic_changes"]:
            print("  Semantic changes:")
            for item in result["semantic_changes"][:10]:
                print(f"    - {item['type']}: {item['description']}")
    return 0 if not should_fail else 1


def run_log(args):
    """Show version history."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    backend = get_storage_backend(store_dir)
    store = backend.versions
    ref = None if args.all else (args.branch or "HEAD")
    if (
        _governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=_current_branch_or_ref(store, ref),
        )
        is None
    ):
        return 1
    versions = store.log(limit=args.limit, ref=ref)

    if not versions:
        print("No version history found.")
        return 0

    current_head = store.resolve_ref("HEAD")
    for v in versions:
        marker = "*" if v.version_id == current_head else " "
        print(f"{marker} {v.version_id}  {v.timestamp}  [{v.source}] ({v.namespace})")
        print(f"    {v.message}")
        print(f"    nodes={v.node_count} edges={v.edge_count}", end="")
        if v.signature:
            print("  signed", end="")
        print()
    return 0


def _rule_from_args(args, effect: str, tenant_id: str) -> "GovernanceRuleRecord":
    from cortex.schemas.memory_v1 import GovernanceRuleRecord

    invalid_actions = [item for item in args.action if item != "*" and item not in GOVERNANCE_ACTION_CHOICES]
    if invalid_actions:
        raise ValueError(f"Unknown governance action(s): {', '.join(sorted(invalid_actions))}")
    return GovernanceRuleRecord(
        tenant_id=tenant_id,
        name=args.name,
        effect=effect,
        actor_pattern=args.actor_pattern,
        actions=list(args.action),
        namespaces=list(args.namespace),
        require_approval=bool(getattr(args, "require_approval", False)),
        approval_below_confidence=getattr(args, "approval_below_confidence", None),
        approval_tags=list(getattr(args, "approval_tag", [])),
        approval_change_types=list(getattr(args, "approval_change", [])),
        description=getattr(args, "description", ""),
    )


def run_governance(args):
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    backend = get_storage_backend(store_dir)
    governance = backend.governance

    if args.governance_subcommand == "list":
        rules = [rule.to_dict() for rule in governance.list_rules()]
        payload = {"rules": rules}
        if _emit_result(payload, args.format) == 0:
            return 0
        if not rules:
            print("No governance rules configured.")
            return 0
        for rule in rules:
            approval = " approval" if rule.get("require_approval") else ""
            print(
                f"{rule['name']}: {rule['effect']} actor={rule['actor_pattern']} "
                f"actions={','.join(rule['actions'])} namespaces={','.join(rule['namespaces'])}{approval}"
            )
        return 0

    if args.governance_subcommand in {"allow", "deny"}:
        try:
            rule = _rule_from_args(args, effect=args.governance_subcommand, tenant_id=backend.tenant_id)
        except ValueError as exc:
            print(str(exc))
            return 1
        governance.upsert_rule(rule)
        payload = {"status": "ok", "rule": rule.to_dict()}
        if _emit_result(payload, args.format) == 0:
            return 0
        print(f"Saved governance rule {rule.name}.")
        return 0

    if args.governance_subcommand == "delete":
        removed = governance.remove_rule(args.name)
        payload = {"status": "ok" if removed else "missing", "name": args.name}
        if _emit_result(payload, args.format) == 0:
            return 0
        if removed:
            print(f"Deleted governance rule {args.name}.")
        else:
            print(f"Governance rule not found: {args.name}")
        return 0 if removed else 1

    if args.governance_subcommand == "check":
        current_graph = None
        baseline_graph = None
        if args.input_file:
            input_path = Path(args.input_file)
            if not input_path.exists():
                print(f"File not found: {input_path}")
                return 1
            current_graph = _load_graph(input_path)
        if args.against:
            store = backend.versions
            baseline_graph = store.checkout(_resolve_version_or_exit(store, args.against))
        decision = governance.authorize(
            args.actor,
            args.action,
            args.namespace,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        )
        if _emit_result(decision.to_dict(), args.format) == 0:
            return 0
        status = "allow" if decision.allowed else "deny"
        print(f"{status.upper()}: actor '{decision.actor}' -> {decision.action} {decision.namespace}")
        if decision.matched_rules:
            print(f"  Rules: {', '.join(decision.matched_rules)}")
        if decision.require_approval:
            print("  Approval required")
        for reason in decision.reasons:
            print(f"  - {reason}")
        return 0 if decision.allowed else 1

    print("Specify a governance subcommand: list, allow, deny, delete, check")
    return 1


def run_remote(args):
    from cortex.schemas.memory_v1 import RemoteRecord
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    backend = get_storage_backend(store_dir)
    store = backend.versions

    if args.remote_subcommand == "list":
        remotes = [
            remote.to_dict() | {"store_path": remote.resolved_store_path} for remote in backend.remotes.list_remotes()
        ]
        payload = {"remotes": remotes}
        if _emit_result(payload, args.format) == 0:
            return 0
        if not remotes:
            print("No remotes configured.")
            return 0
        for remote in remotes:
            allowed = ", ".join(remote.get("allowed_namespaces", []) or [remote["default_branch"]])
            did = str(remote.get("trusted_did") or "")[:24]
            print(
                f"{remote['name']}: {remote['store_path']} (default={remote['default_branch']}, "
                f"allow={allowed}, did={did}...)"
            )
        return 0

    if args.remote_subcommand == "add":
        remote = RemoteRecord(
            tenant_id=backend.tenant_id,
            name=args.name,
            path=args.path,
            default_branch=args.default_branch,
            allowed_namespaces=list(args.allow_namespace or []),
        )
        try:
            backend.remotes.add_remote(remote)
        except ValueError as exc:
            print(str(exc))
            return 1
        stored = next(item for item in backend.remotes.list_remotes() if item.name == args.name)
        payload = {"status": "ok", "remote": stored.to_dict() | {"store_path": stored.resolved_store_path}}
        if _emit_result(payload, args.format) == 0:
            return 0
        allowed = ", ".join(stored.allowed_namespaces or [stored.default_branch])
        print(f"Added remote {stored.name} -> {stored.resolved_store_path}")
        print(f"  trusted DID: {stored.trusted_did}")
        print(f"  allowed namespaces: {allowed}")
        return 0

    if args.remote_subcommand == "remove":
        removed = backend.remotes.remove_remote(args.name)
        payload = {"status": "ok" if removed else "missing", "name": args.name}
        if _emit_result(payload, args.format) == 0:
            return 0
        if removed:
            print(f"Removed remote {args.name}.")
        else:
            print(f"Remote not found: {args.name}")
        return 0 if removed else 1

    remotes_by_name = {remote.name: remote for remote in backend.remotes.list_remotes()}
    remote = remotes_by_name.get(args.name)
    if remote is None:
        print(f"Remote not found: {args.name}")
        return 1

    if args.remote_subcommand == "push":
        namespace = _current_branch_or_ref(store, args.branch)
        if (
            _governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="push",
                namespace=namespace,
            )
            is None
        ):
            return 1
        try:
            payload = backend.remotes.push_remote(
                args.name,
                branch=args.branch,
                target_branch=args.to_branch,
                force=args.force,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        if _emit_result(payload, args.format) == 0:
            return 0
        print(f"Pushed {payload['branch']} -> {remote.name}:{payload['remote_branch']} ({payload['head']})")
        print(f"  trusted remote: {payload['trusted_remote_did']}")
        print(f"  receipt: {payload['receipt_path']}")
        return 0

    if args.remote_subcommand == "pull":
        remote_branch = args.branch or remote.default_branch
        namespace = args.into_branch or f"remotes/{remote.name}/{remote_branch}"
        if (
            _governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="pull",
                namespace=namespace,
            )
            is None
        ):
            return 1
        try:
            payload = backend.remotes.pull_remote(
                args.name,
                branch=remote_branch,
                into_branch=args.into_branch,
                force=args.force,
                switch=args.switch,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        if _emit_result(payload, args.format) == 0:
            return 0
        print(f"Pulled {remote.name}:{remote_branch} -> {payload['branch']} ({payload['head']})")
        print(f"  trusted remote: {payload['trusted_remote_did']}")
        print(f"  receipt: {payload['receipt_path']}")
        return 0

    if args.remote_subcommand == "fork":
        remote_branch = args.remote_branch or remote.default_branch
        if (
            _governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="branch",
                namespace=args.branch_name,
            )
            is None
        ):
            return 1
        try:
            payload = backend.remotes.fork_remote(
                args.name,
                remote_branch=remote_branch,
                local_branch=args.branch_name,
                switch=args.switch,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        if _emit_result(payload, args.format) == 0:
            return 0
        print(f"Forked {remote.name}:{remote_branch} -> {args.branch_name} ({payload['head']})")
        print(f"  trusted remote: {payload['trusted_remote_did']}")
        print(f"  receipt: {payload['receipt_path']}")
        return 0

    print("Specify a remote subcommand: list, add, remove, push, pull, fork")
    return 1


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


def run_pack(args):
    from cortex.packs import (
        ask_pack,
        compile_pack,
        export_pack_bundle,
        import_pack_bundle,
        ingest_pack,
        init_pack,
        lint_pack,
        list_packs,
        mount_pack,
        pack_status,
        query_pack,
        render_pack_context,
    )

    store_dir = _resolved_store_dir(args.store_dir)

    if args.pack_subcommand == "init":
        try:
            payload = init_pack(
                store_dir,
                args.name,
                description=args.description,
                owner=args.owner,
            )
        except (FileExistsError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Created Brainpack `{payload['pack']}` at {payload['path']}")
        return 0

    if args.pack_subcommand == "list":
        payload = list_packs(store_dir)
        if _emit_result(payload, args.format) == 0:
            return 0
        if not payload["packs"]:
            _echo("No Brainpacks found yet.")
            return 0
        _echo(f"Found {payload['count']} Brainpack(s):\n")
        for item in payload["packs"]:
            compiled = item["compiled_at"] or "not compiled yet"
            _echo(
                f"  {item['pack']:<18} {item['source_count']:>3} sources  "
                f"{item['graph_nodes']:>3} nodes  {item['article_count']:>3} wiki pages  {compiled}"
            )
        return 0

    if args.pack_subcommand == "ingest":
        try:
            payload = ingest_pack(
                store_dir,
                args.name,
                args.paths,
                mode=args.mode,
                source_type=args.source_type,
                recurse=args.recurse,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Ingested {payload['ingested_count']} source(s) into `{payload['pack']}`.")
        _echo(f"Total indexed sources: {payload['source_count']}")
        return 0

    if args.pack_subcommand == "compile":
        try:
            payload = compile_pack(
                store_dir,
                args.name,
                incremental=args.incremental,
                suggest_questions=args.suggest_questions,
                max_summary_chars=args.max_summary_chars,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Compiled `{payload['pack']}`:")
        _echo(f"  sources: {payload['source_count']} total, {payload['text_source_count']} readable")
        _echo(f"  graph: {payload['graph_nodes']} nodes / {payload['graph_edges']} edges")
        _echo(f"  wiki: {payload['article_count']} page(s)")
        _echo(f"  claims: {payload['claim_count']}")
        _echo(f"  unknowns: {payload['unknown_count']}")
        _echo(f"  graph path: {payload['graph_path']}")
        return 0

    if args.pack_subcommand == "status":
        try:
            payload = pack_status(store_dir, args.name)
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Brainpack `{payload['pack']}`")
        if payload["manifest"]["description"]:
            _echo(f"  {payload['manifest']['description']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"{payload['source_count']} sources",
                    f"{payload['graph_nodes']} graph nodes",
                    f"{payload['article_count']} wiki pages",
                    f"{payload['claim_count']} claims",
                    f"{payload['unknown_count']} unknowns",
                ]
            )
        )
        _echo(f"  compiled: {payload['compiled_at'] or 'not compiled yet'}")
        return 0

    if args.pack_subcommand == "context":
        try:
            payload = render_pack_context(
                store_dir,
                args.name,
                target=args.target,
                smart=args.smart,
                policy_name=args.policy,
                max_chars=args.max_chars,
                project_dir=args.project or "",
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Brainpack `{payload['pack']}` → {payload['name']}")
        _echo(f"  {payload['fact_count']} routed facts via {payload['mode']} mode")
        if payload["context_markdown"]:
            _echo("")
            _echo(payload["context_markdown"], force=True)
        elif payload["message"]:
            _echo(payload["message"])
        return 0

    if args.pack_subcommand == "mount":
        try:
            payload = mount_pack(
                store_dir,
                args.name,
                targets=args.to,
                project_dir=args.project or "",
                smart=args.smart,
                policy_name=args.policy,
                max_chars=args.max_chars,
                openclaw_store_dir=args.openclaw_store_dir,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Mounted Brainpack `{payload['pack']}`:")
        for item in payload["targets"]:
            note = f"  {item['note']}" if item.get("note") else ""
            _echo(f"  {item['target']:<12} {item['status']}{note}")
            for path in item.get("paths", []):
                _echo(f"    → {path}")
        return 0

    if args.pack_subcommand == "query":
        try:
            payload = query_pack(
                store_dir,
                args.name,
                args.query,
                limit=args.limit,
                mode=args.mode,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Brainpack `{payload['pack']}` query: {payload['query']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"{payload['total_matches']} ranked matches",
                    f"{payload['counts']['claims']} claims",
                    f"{payload['counts']['wiki']} source pages",
                    f"{payload['counts']['artifacts']} artifacts",
                ]
            )
        )
        if not payload["results"]:
            _echo("  No strong matches yet. Try compiling more sources or broadening the query.")
            return 0
        _echo("")
        for item in payload["results"]:
            extra = item.get("path") or item.get("source_path") or ""
            suffix = f" ({extra})" if extra else ""
            _echo(f"- [{item['kind']}] {item['title']}: {item.get('summary', '')}{suffix}".rstrip())
        return 0

    if args.pack_subcommand == "ask":
        try:
            payload = ask_pack(
                store_dir,
                args.name,
                args.question,
                output=args.output,
                limit=args.limit,
                write_back=args.write_back,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Brainpack `{payload['pack']}` answered: {payload['question']}")
        _echo(f"  {payload['summary']}")
        if payload["artifact_written"]:
            _echo(f"  saved: {payload['artifact_path']}")
        elif payload["message"]:
            _echo(f"  {payload['message']}")
        _echo("")
        _echo(payload["answer_markdown"], force=True)
        return 0

    if args.pack_subcommand == "lint":
        try:
            payload = lint_pack(
                store_dir,
                args.name,
                stale_days=args.stale_days,
                duplicate_threshold=args.duplicate_threshold,
                weak_claim_confidence=args.weak_claim_confidence,
                thin_article_chars=args.thin_article_chars,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Brainpack `{payload['pack']}` lint: {payload['lint_status']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"{payload['summary']['total_findings']} findings",
                    f"{payload['summary']['high']} high",
                    f"{payload['summary']['medium']} medium",
                    f"{payload['summary']['low']} low",
                ]
            )
        )
        if payload["findings"]:
            _echo("")
            for item in payload["findings"][:8]:
                _echo(f"- [{item['level']}] {item['title']}: {item['detail']}")
        else:
            _echo("  No Brainpack integrity issues detected.")
        if payload["suggestions"]:
            _echo("")
            _echo("Suggestions:")
            for suggestion in payload["suggestions"]:
                _echo(f"- {suggestion}")
        return 0

    if args.pack_subcommand == "export":
        try:
            payload = export_pack_bundle(
                store_dir,
                args.name,
                args.output,
                verify=not args.no_verify,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Exported Brainpack `{payload['pack']}`")
        _echo(f"  archive: {payload['archive']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"{payload['file_count']} files",
                    f"{payload['materialized_reference_sources']} materialized reference source(s)",
                    "verified" if payload["verified"] else "not verified",
                ]
            )
        )
        if payload["missing_reference_sources"]:
            _echo("  Missing reference sources:")
            for item in payload["missing_reference_sources"][:8]:
                _echo(f"  - {item}")
        return 0

    if args.pack_subcommand == "import":
        try:
            payload = import_pack_bundle(
                args.archive,
                store_dir,
                as_name=args.as_name,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Imported Brainpack `{payload['pack']}` from {payload['archive']}")
        if payload["pack"] != payload["original_pack"]:
            _echo(f"  original pack: {payload['original_pack']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"{payload['source_count']} sources",
                    f"{payload['artifact_count']} artifacts",
                    payload["compile_status"],
                ]
            )
        )
        return 0

    return _error(
        "Specify a pack subcommand: init, list, ingest, compile, status, context, mount, query, ask, lint, export, import"
    )


def run_mind(args):
    from cortex.minds import (
        attach_pack_to_mind,
        clear_default_mind,
        compose_mind,
        default_mind_status,
        detach_pack_from_mind,
        ingest_detected_sources_into_mind,
        init_mind,
        list_mind_mounts,
        list_minds,
        mind_status,
        mount_mind,
        remember_on_mind,
        set_default_mind,
    )

    store_dir = _resolved_store_dir(args.store_dir)

    if args.mind_subcommand == "init":
        try:
            payload = init_mind(
                store_dir,
                args.name,
                kind=args.kind,
                label=args.label,
                owner=args.owner,
                default_policy=args.default_policy,
            )
        except (FileExistsError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Created Mind `{payload['mind']}` at {payload['path']}")
        return 0

    if args.mind_subcommand == "list":
        payload = list_minds(store_dir)
        if _emit_result(payload, args.format) == 0:
            return 0
        if not payload["minds"]:
            _echo("No Cortex Minds found yet.")
            return 0
        _echo(f"Found {payload['count']} Mind(s):\n")
        for item in payload["minds"]:
            suffix = "  default" if item.get("is_default") else ""
            _echo(
                f"  {item['mind']:<18} {item['kind']:<8} "
                f"{item['attachment_count']:>2} packs  {item['mount_count']:>2} mounts  "
                f"{item['current_branch']}{suffix}"
            )
        return 0

    if args.mind_subcommand == "default":
        try:
            if args.clear:
                payload = clear_default_mind(store_dir)
            elif args.name:
                payload = set_default_mind(store_dir, args.name)
            else:
                payload = default_mind_status(store_dir)
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        if payload["configured"]:
            _echo(f"Default Mind: `{payload['mind']}` ({payload['source']})")
        else:
            _echo("No default Mind configured.")
        return 0

    if args.mind_subcommand == "ingest":
        project_dir = Path(args.project) if getattr(args, "project", None) else Path.cwd()
        try:
            redactor = _build_pii_redactor(
                args,
                default_enabled=not getattr(args, "no_redact_detected", False),
            )
        except FileNotFoundError as exc:
            return _missing_path_error(Path(exc.args[0]), label="Redaction patterns file")
        if redactor is not None and args.format != "json":
            if not args.redact:
                _echo("PII redaction enabled for detected local sources")
            else:
                _echo("PII redaction enabled")
        try:
            payload = ingest_detected_sources_into_mind(
                store_dir,
                args.name,
                targets=list(getattr(args, "from_detected", []) or []),
                project_dir=project_dir,
                extra_roots=[Path(root) for root in getattr(args, "search_root", [])],
                include_config_metadata=bool(getattr(args, "include_config_metadata", False)),
                include_unmanaged_text=bool(getattr(args, "include_unmanaged_text", False)),
                redactor=redactor,
                message=args.message,
            )
        except (FileNotFoundError, ValueError) as exc:
            lines = str(exc).splitlines()
            return _error(lines[0], hint="\n".join(lines[1:]) or None)
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(
            f"Mind `{payload['mind']}` queued {payload['proposed_source_count']} detected source(s)"
            f" for review as `{payload['proposal_id']}`"
        )
        _echo(
            "  "
            + " · ".join(
                [
                    f"{payload['graph_node_count']} nodes",
                    f"{payload['graph_edge_count']} edges",
                    payload["proposal_path"],
                ]
            )
        )
        return 0

    if args.mind_subcommand == "status":
        try:
            payload = mind_status(store_dir, args.name)
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Mind `{payload['mind']}`")
        _echo(f"  {payload['manifest']['label']} · {payload['manifest']['kind']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"branch {payload['manifest']['current_branch']}",
                    f"{payload['attachment_count']} attached Brainpacks",
                    f"{payload['attached_mount_count']} attached pack mounts",
                    f"{payload['mount_count']} direct mind mounts",
                    payload["default_disclosure"],
                    "default" if payload.get("is_default") else "non-default",
                ]
            )
        )
        _echo(f"  graph ref: {payload['graph_ref']}")
        if payload["attached_brainpacks"]:
            _echo("  attached packs:")
            for item in payload["attached_brainpacks"]:
                extra = []
                if item["activation"]["always_on"]:
                    extra.append("always-on")
                if item["activation"]["targets"]:
                    extra.append("targets=" + ",".join(item["activation"]["targets"]))
                if item["mounted_targets"]:
                    extra.append("mounted=" + ",".join(item["mounted_targets"]))
                suffix = f" ({'; '.join(extra)})" if extra else ""
                _echo(f"    - {item['pack']} · {item['compile_status']} · priority {item['priority']}{suffix}")
        return 0

    if args.mind_subcommand == "remember":
        try:
            payload = remember_on_mind(
                store_dir,
                args.name,
                statement=args.statement,
                message=args.message,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Mind `{payload['mind']}` remembered:")
        _echo(f"  {payload['statement']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"branch {payload['branch']}",
                    f"{payload['graph_node_count']} nodes",
                    f"{payload['graph_edge_count']} edges",
                ]
            )
        )
        if payload["targets"]:
            _echo("  refreshed mounts:")
            for item in payload["targets"]:
                note = f"  {item['note']}" if item.get("note") else ""
                _echo(f"    {item['target']:<12} {item.get('status', 'ok')}{note}")
        else:
            _echo("  no persisted mounts to refresh.")
        return 0

    if args.mind_subcommand == "attach-pack":
        try:
            payload = attach_pack_to_mind(
                store_dir,
                args.name,
                args.pack,
                priority=args.priority,
                always_on=args.always_on,
                targets=args.target,
                task_terms=args.task_term,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        verb = "Updated" if payload["updated"] else "Attached"
        _echo(f"{verb} Brainpack `{payload['pack']}` on Mind `{payload['mind']}`")
        _echo(f"  total attachments: {payload['attachment_count']}")
        return 0

    if args.mind_subcommand == "detach-pack":
        try:
            payload = detach_pack_from_mind(
                store_dir,
                args.name,
                args.pack,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Detached Brainpack `{payload['pack']}` from Mind `{payload['mind']}`")
        _echo(f"  total attachments: {payload['attachment_count']}")
        return 0

    if args.mind_subcommand == "compose":
        try:
            payload = compose_mind(
                store_dir,
                args.name,
                target=args.to,
                task=args.task,
                project_dir=args.project or "",
                smart=args.smart,
                policy_name=args.policy,
                max_chars=args.max_chars,
                activation_target=args.activation_target,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Mind `{payload['mind']}` → {payload['name']}")
        _echo(
            "  "
            + " · ".join(
                [
                    f"branch {payload['branch']}",
                    f"{payload['fact_count']} routed facts",
                    f"{payload['included_brainpack_count']} attached packs included",
                    payload["policy"],
                ]
            )
        )
        if payload["included_brainpacks"]:
            _echo("  included packs: " + ", ".join(item["pack"] for item in payload["included_brainpacks"]))
        if payload["context_markdown"]:
            _echo("")
            _echo(payload["context_markdown"], force=True)
        elif payload["message"]:
            _echo(payload["message"])
        return 0

    if args.mind_subcommand == "mount":
        try:
            payload = mount_mind(
                store_dir,
                args.name,
                targets=args.to,
                task=args.task,
                project_dir=args.project or "",
                smart=args.smart,
                policy_name=args.policy,
                max_chars=args.max_chars,
                openclaw_store_dir=args.openclaw_store_dir,
            )
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Mounted Mind `{payload['mind']}`:")
        for item in payload["targets"]:
            note = f"  {item['note']}" if item.get("note") else ""
            _echo(f"  {item['target']:<12} {item['status']}{note}")
            for path in item.get("paths", []):
                _echo(f"    → {path}")
        _echo(f"  total persisted mounts: {payload['mount_count']}")
        return 0

    if args.mind_subcommand == "mounts":
        try:
            payload = list_mind_mounts(store_dir, args.name)
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo(f"Mind `{payload['mind']}` mount records")
        if not payload["mounts"]:
            _echo("  No persisted mounts yet.")
            return 0
        for item in payload["mounts"]:
            extra = []
            if item.get("task"):
                extra.append(f"task={item['task']}")
            if item.get("activation_target") and item["activation_target"] != item["target"]:
                extra.append(f"activation={item['activation_target']}")
            suffix = f" ({'; '.join(extra)})" if extra else ""
            _echo(f"  {item['target']:<12} {item.get('status', 'ok')}{suffix}")
            for path in item.get("paths", []):
                _echo(f"    → {path}")
        return 0

    return _error(
        "Specify a mind subcommand: init, list, status, default, ingest, remember, attach-pack, detach-pack, compose, mount, mounts"
    )


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
    """Show statistics for a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("schema_version", "")
    if version.startswith("5"):
        graph = CortexGraph.from_v5_json(data)
    else:
        graph = upgrade_v4_to_v5(data)

    st = graph.stats()
    print(f"Nodes: {st['node_count']}")
    print(f"Edges: {st['edge_count']}")
    print(f"Avg degree: {st['avg_degree']}")
    if st.get("isolated_nodes", 0) > 0:
        print(f"Isolated nodes (0 edges): {st['isolated_nodes']}")
    if st["tag_distribution"]:
        print("Tag distribution:")
        for tag, count in sorted(st["tag_distribution"].items(), key=lambda x: -x[1]):
            print(f"  {tag}: {count}")
    if st.get("relation_distribution"):
        print("Relation distribution:")
        for rel, count in sorted(st["relation_distribution"].items(), key=lambda x: -x[1]):
            print(f"  {rel}: {count}")
    if st.get("top_central_nodes"):
        print(f"Top central nodes: {', '.join(st['top_central_nodes'])}")
    return 0


def run_pull(args):
    """Import a platform export file back into a CortexGraph."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    adapter = ADAPTERS.get(args.from_platform)
    if adapter is None:
        print(f"Unknown platform: {args.from_platform}")
        return 1

    try:
        graph = adapter.pull(input_path)
    except Exception as e:
        print(f"Error parsing {input_path}: {e}")
        return 1

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_graph.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")

    st = graph.stats()
    print(f"Imported from {args.from_platform}: {st['node_count']} nodes, {st['edge_count']} edges")
    print(f"Saved to: {output_path}")
    return 0


def run_rotate(args):
    """Rotate UPAI identity key."""
    from cortex.upai.identity import UPAIIdentity
    from cortex.upai.keychain import Keychain

    store_dir = Path(args.store_dir)
    if not (store_dir / "identity.json").exists():
        print(f"No identity found in {store_dir}. Run: cortex identity --init")
        return 1

    identity = UPAIIdentity.load(store_dir)
    kc = Keychain(store_dir)

    new_identity, proof = kc.rotate(identity, reason=args.reason)
    print(f"Old DID: {identity.did}")
    print(f"New DID: {new_identity.did}")
    print(f"Reason: {args.reason}")
    if proof:
        print(f"Revocation proof: {proof[:32]}...")
    print("Identity rotated successfully.")
    return 0


def run_completion(args):
    """Generate shell completion script."""
    from cortex.completion import generate_completion

    parser = build_parser()
    script = generate_completion(parser, args.shell)
    print(script)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv=None):
    global _CLI_QUIET

    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)

    argv, force_json, quiet = _extract_global_flags(argv)
    _CLI_QUIET = quiet or force_json

    # Default-subcommand routing: if the first arg is not a known subcommand,
    # treat it as a file path and route to the "migrate" subcommand.
    known_subcommands = (
        "init",
        "connect",
        "serve",
        "extract",
        "ingest",
        "import",
        "memory",
        "migrate",
        "query",
        "stats",
        "timeline",
        "contradictions",
        "drift",
        "diff",
        "blame",
        "history",
        "claim",
        "checkout",
        "rollback",
        "identity",
        "commit",
        "branch",
        "switch",
        "merge",
        "review",
        "log",
        "governance",
        "remote",
        "sync",
        "verify",
        "gaps",
        "digest",
        "viz",
        "watch",
        "sync-schedule",
        "extract-coding",
        "context-hook",
        "context-export",
        "context-write",
        "portable",
        "scan",
        "remember",
        "status",
        "build",
        "audit",
        "doctor",
        "help",
        "mind",
        "ui",
        "pack",
        "benchmark",
        "server",
        "mcp",
        "backup",
        "openapi",
        "release-notes",
        "rotate",
        "pull",
        "completion",
        "-h",
        "--help",
        "--help-all",
    )
    if argv and argv[0] not in known_subcommands:
        argv = ["migrate"] + list(argv)

    parser = build_parser()
    args = parser.parse_args(argv)
    setattr(args, "json_output", force_json)
    setattr(args, "quiet", quiet)

    if getattr(args, "help_all", False):
        parser.show_all_commands = True
        print(parser.format_help(), end="")
        return 0

    if args.subcommand is None:
        parser.print_help()
        return 1

    if force_json:
        if hasattr(args, "format"):
            args.format = "json"
        elif args.subcommand not in {"extract"}:
            return _error(f"`--json` is not supported for '{args.subcommand}'.")

    if args.subcommand == "init":
        return run_init(args)
    elif args.subcommand == "help":
        return run_help_topic(args)
    elif args.subcommand == "connect":
        return run_connect(args)
    elif args.subcommand == "serve":
        return run_serve(args)
    elif args.subcommand == "extract":
        return run_extract(args)
    elif args.subcommand == "ingest":
        return run_ingest(args)
    elif args.subcommand == "import":
        return run_import(args)
    elif args.subcommand == "memory":
        if args.memory_subcommand == "conflicts":
            return run_memory_conflicts(args)
        elif args.memory_subcommand == "show":
            return run_memory_show(args)
        elif args.memory_subcommand == "forget":
            return run_memory_forget(args)
        elif args.memory_subcommand == "retract":
            return run_memory_retract(args)
        elif args.memory_subcommand == "set":
            return run_memory_set(args)
        elif args.memory_subcommand == "resolve":
            return run_memory_resolve(args)
        print("Specify a memory subcommand: conflicts, show, forget, retract, set, resolve")
        return 1
    elif args.subcommand == "query":
        return run_query(args)
    elif args.subcommand == "stats":
        return run_stats(args)
    elif args.subcommand == "timeline":
        return run_timeline(args)
    elif args.subcommand == "contradictions":
        return run_contradictions(args)
    elif args.subcommand == "drift":
        return run_drift(args)
    elif args.subcommand == "diff":
        return run_diff(args)
    elif args.subcommand == "blame":
        return run_blame(args)
    elif args.subcommand == "history":
        return run_history(args)
    elif args.subcommand == "claim":
        if args.claim_subcommand == "log":
            return run_claim_log(args)
        elif args.claim_subcommand == "show":
            return run_claim_show(args)
        elif args.claim_subcommand == "accept":
            return run_claim_accept(args)
        elif args.claim_subcommand == "reject":
            return run_claim_reject(args)
        elif args.claim_subcommand == "supersede":
            return run_claim_supersede(args)
        print("Specify a claim subcommand: log, show, accept, reject, supersede")
        return 1
    elif args.subcommand == "checkout":
        return run_checkout(args)
    elif args.subcommand == "rollback":
        return run_rollback(args)
    elif args.subcommand == "identity":
        return run_identity(args)
    elif args.subcommand == "commit":
        return run_commit(args)
    elif args.subcommand == "branch":
        return run_branch(args)
    elif args.subcommand == "switch":
        return run_switch(args)
    elif args.subcommand == "merge":
        return run_merge(args)
    elif args.subcommand == "review":
        return run_review(args)
    elif args.subcommand == "log":
        return run_log(args)
    elif args.subcommand == "governance":
        return run_governance(args)
    elif args.subcommand == "remote":
        return run_remote(args)
    elif args.subcommand == "sync":
        return run_sync(args)
    elif args.subcommand == "verify":
        return run_verify(args)
    elif args.subcommand == "gaps":
        return run_gaps(args)
    elif args.subcommand == "digest":
        return run_digest(args)
    elif args.subcommand == "viz":
        return run_viz(args)
    elif args.subcommand == "watch":
        return run_watch(args)
    elif args.subcommand == "sync-schedule":
        return run_sync_schedule(args)
    elif args.subcommand == "extract-coding":
        return run_extract_coding(args)
    elif args.subcommand == "context-hook":
        return run_context_hook(args)
    elif args.subcommand == "context-export":
        return run_context_export(args)
    elif args.subcommand == "pull":
        return run_pull(args)
    elif args.subcommand == "rotate":
        return run_rotate(args)
    elif args.subcommand == "context-write":
        return run_context_write(args)
    elif args.subcommand == "portable":
        return run_portable(args)
    elif args.subcommand == "scan":
        return run_scan(args)
    elif args.subcommand == "remember":
        return run_remember(args)
    elif args.subcommand == "status":
        return run_status(args)
    elif args.subcommand == "build":
        return run_build(args)
    elif args.subcommand == "audit":
        return run_audit(args)
    elif args.subcommand == "doctor":
        return run_doctor(args)
    elif args.subcommand == "mind":
        return run_mind(args)
    elif args.subcommand == "pack":
        return run_pack(args)
    elif args.subcommand == "ui":
        return run_ui(args)
    elif args.subcommand == "benchmark":
        return run_benchmark(args)
    elif args.subcommand == "backup":
        return run_backup(args)
    elif args.subcommand == "openapi":
        return run_openapi(args)
    elif args.subcommand == "release-notes":
        return run_release_notes(args)
    elif args.subcommand == "server":
        return run_server(args)
    elif args.subcommand == "mcp":
        return run_mcp(args)
    elif args.subcommand == "completion":
        return run_completion(args)
    else:
        return run_migrate(args)


if __name__ == "__main__":
    sys.exit(main())
