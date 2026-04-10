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
from typing import TYPE_CHECKING, Any

from cortex import cli_runtime as cli_runtime_module
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
from cortex.upai.disclosure import BUILTIN_POLICIES

if TYPE_CHECKING:
    from cortex.claims import ClaimEvent
    from cortex.schemas.memory_v1 import GovernanceRuleRecord
    from cortex.upai.identity import UPAIIdentity

ADVANCED_HELP_NOTE = cli_surface_module.ADVANCED_HELP_NOTE
CONNECT_RUNTIME_TARGETS = cli_surface_module.CONNECT_RUNTIME_TARGETS
CortexArgumentParser = cli_surface_module.CortexArgumentParser
FIRST_CLASS_COMMANDS = cli_surface_module.FIRST_CLASS_COMMANDS
MIND_HELP_EPILOG = cli_surface_module.MIND_HELP_EPILOG
PACK_HELP_EPILOG = cli_surface_module.PACK_HELP_EPILOG
add_setup_and_runtime_parsers = cli_surface_module.add_setup_and_runtime_parsers
_add_runtime_security_args = cli_runtime_module._add_runtime_security_args
_doctor_has_store_signature = cli_workspace_commands_module._doctor_has_store_signature
_doctor_is_cortex_config = cli_workspace_commands_module._doctor_is_cortex_config
_doctor_raw_config_payload = cli_workspace_commands_module._doctor_raw_config_payload
_doctor_store_entries = cli_workspace_commands_module._doctor_store_entries

GOVERNANCE_ACTION_CHOICES = ("branch", "merge", "pull", "push", "read", "rollback", "write")
_CLI_QUIET = False


# ---------------------------------------------------------------------------
# Platform → format-key mapping
# ---------------------------------------------------------------------------
PLATFORM_FORMATS = {
    "claude": ["claude-preferences", "claude-memories"],
    "notion": ["notion", "notion-db"],
    "gdocs": ["gdocs"],
    "system-prompt": ["system-prompt"],
    "summary": ["summary"],
    "full": ["full"],
    "all": [
        "claude-preferences",
        "claude-memories",
        "system-prompt",
        "notion",
        "notion-db",
        "gdocs",
        "summary",
        "full",
    ],
}

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


def build_parser(*, show_all_commands: bool = False):
    parser = CortexArgumentParser(
        prog="cortex",
        description="Cortex — one portable Mind across AI tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        show_all_commands=show_all_commands,
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output when supported")
    parser.add_argument("--quiet", action="store_true", help="Suppress human-readable success output")
    parser.add_argument("--help-all", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="subcommand")

    add_setup_and_runtime_parsers(sub, add_runtime_security_args=_add_runtime_security_args)

    # -- migrate (default) --------------------------------------------------
    mig = sub.add_parser("migrate", help="Full pipeline: extract then import")
    mig.add_argument("input_file", help="Path to chat export file")
    mig.add_argument(
        "--to",
        "-t",
        dest="to",
        default="all",
        choices=list(PLATFORM_FORMATS.keys()),
        help="Target platform shortcut (default: all)",
    )
    mig.add_argument("--output", "-o", default="./output", help="Output directory")
    mig.add_argument(
        "--input-format",
        "-F",
        choices=[
            "auto",
            "openai",
            "gemini",
            "perplexity",
            "grok",
            "cursor",
            "windsurf",
            "copilot",
            "jsonl",
            "api_logs",
            "messages",
            "text",
            "generic",
        ],
        default="auto",
        help="Override input format auto-detection",
    )
    mig.add_argument("--merge", "-m", help="Existing context file to merge with")
    mig.add_argument("--redact", action="store_true", help="Enable PII redaction")
    mig.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    mig.add_argument("--confidence", "-c", choices=["high", "medium", "low", "all"], default="medium")
    mig.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mig.add_argument("--verbose", "-v", action="store_true")
    mig.add_argument("--stats", action="store_true", help="Show category stats")
    mig.add_argument(
        "--schema",
        choices=["v5", "v4"],
        default="v5",
        help="Output context.json schema version (default: v5; v4 is deprecated)",
    )
    mig.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    mig.add_argument("--no-claims", action="store_true", help="Skip provenance stamping and claim-ledger recording")
    mig.add_argument(
        "--discover-edges", action="store_true", help="Run smart edge extraction (pattern + co-occurrence)"
    )
    mig.add_argument("--llm", action="store_true", help="LLM-assisted edge extraction (future, stub)")

    # -- extract ------------------------------------------------------------
    ext = sub.add_parser("extract", help="Extract context from export file")
    ext.add_argument("input_file", nargs="?", help="Path to chat export file")
    ext.add_argument("--output", "-o", help="Output JSON path")
    ext.add_argument(
        "--format",
        "-f",
        choices=[
            "auto",
            "openai",
            "gemini",
            "perplexity",
            "grok",
            "cursor",
            "windsurf",
            "copilot",
            "jsonl",
            "api_logs",
            "messages",
            "text",
            "generic",
        ],
        default="auto",
    )
    ext.add_argument("--merge", "-m", help="Existing context file to merge with")
    ext.add_argument("--redact", action="store_true")
    ext.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    ext.add_argument("--verbose", "-v", action="store_true")
    ext.add_argument("--stats", action="store_true")
    ext.add_argument(
        "--from-detected",
        nargs="+",
        help="Explicitly adopt detected local platform sources instead of a raw export file",
    )
    ext.add_argument("--project", "-d", help="Project directory for detected local sources (default: cwd)")
    ext.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for detected exports (repeatable)",
    )
    ext.add_argument(
        "--include-config-metadata",
        action="store_true",
        help="Also ingest detected MCP config metadata; config files are metadata-only by default",
    )
    ext.add_argument(
        "--include-unmanaged-text",
        action="store_true",
        help="Also ingest unmanaged text outside Cortex markers from detected instruction files",
    )
    ext.add_argument(
        "--no-redact-detected",
        action="store_true",
        help="Disable the default PII redaction applied to detected local source adoption",
    )
    ext.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    ext.add_argument("--no-claims", action="store_true", help="Skip provenance stamping and claim-ledger recording")

    # -- ingest -------------------------------------------------------------
    ing = sub.add_parser("ingest", help="Normalize GitHub/Slack/docs sources and extract memory")
    ing.add_argument("kind", choices=["github", "slack", "docs"], help="Connector kind")
    ing.add_argument("input_file", help="Path to connector export file or directory")
    ing.add_argument("--output", "-o", help="Output JSON path")
    ing.add_argument("--merge", "-m", help="Existing context file to merge with")
    ing.add_argument("--redact", action="store_true")
    ing.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    ing.add_argument("--preview", action="store_true", help="Print normalized connector text without extracting")
    ing.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    ing.add_argument("--no-claims", action="store_true", help="Skip provenance stamping and claim-ledger recording")

    # -- import -------------------------------------------------------------
    imp = sub.add_parser("import", help="Import context to platform formats")
    imp.add_argument("input_file", help="Path to context JSON file")
    imp.add_argument(
        "--to",
        "-t",
        dest="to",
        default="all",
        choices=list(PLATFORM_FORMATS.keys()),
        help="Target platform shortcut (default: all)",
    )
    imp.add_argument("--output", "-o", default="./output", help="Output directory")
    imp.add_argument("--confidence", "-c", choices=["high", "medium", "low", "all"], default="medium")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--verbose", "-v", action="store_true")

    mem = sub.add_parser("memory", help="Inspect and edit local memory graph")
    mem_sub = mem.add_subparsers(dest="memory_subcommand")

    mem_conf = mem_sub.add_parser("conflicts", help="List memory conflicts")
    mem_conf.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_conf.add_argument("--severity", type=float, default=0.0, help="Minimum severity threshold (0.0-1.0)")
    mem_conf.add_argument("--format", choices=["json", "text"], default="text")

    mem_show = mem_sub.add_parser("show", help="Show memory nodes")
    mem_show.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_show.add_argument("--label", help="Exact node label")
    mem_show.add_argument("--tag", help="Filter by tag")
    mem_show.add_argument("--limit", type=int, default=20, help="Max nodes to show")
    mem_show.add_argument("--format", choices=["json", "text"], default="text")

    mem_forget = mem_sub.add_parser("forget", help="Forget memory nodes")
    mem_forget.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_forget.add_argument("--node-id", help="Delete by node ID")
    mem_forget.add_argument("--label", help="Delete by exact label")
    mem_forget.add_argument("--tag", help="Delete all nodes with tag")
    mem_forget.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mem_forget.add_argument("--commit-message", help="Optional version commit message")
    mem_forget.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_forget.add_argument("--format", choices=["json", "text"], default="text")

    mem_retract = mem_sub.add_parser("retract", help="Retract memory evidence by provenance source")
    mem_retract.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_retract.add_argument("--source", required=True, help="Provenance source label to retract")
    mem_retract.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mem_retract.add_argument(
        "--keep-orphans",
        action="store_true",
        help="Keep touched nodes and edges even if they no longer have any source-backed evidence",
    )
    mem_retract.add_argument("--commit-message", help="Optional version commit message")
    mem_retract.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_retract.add_argument("--format", choices=["json", "text"], default="text")

    mem_set = mem_sub.add_parser("set", help="Create or update a memory node")
    mem_set.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_set.add_argument("--label", required=True, help="Node label")
    mem_set.add_argument("--tag", action="append", required=True, help="Tag to apply (repeatable)")
    mem_set.add_argument("--brief", default="", help="Short summary")
    mem_set.add_argument("--description", default="", help="Long description")
    mem_set.add_argument("--property", action="append", help="Node property key=value (repeatable)")
    mem_set.add_argument("--alias", action="append", help="Alternate label/alias (repeatable)")
    mem_set.add_argument("--confidence", type=float, default=0.95, help="Confidence score")
    mem_set.add_argument("--valid-from", default="", help="Validity start timestamp (ISO-8601)")
    mem_set.add_argument("--valid-to", default="", help="Validity end timestamp (ISO-8601)")
    mem_set.add_argument("--status", default="", help="Lifecycle status such as active, planned, or historical")
    mem_set.add_argument("--source", default="", help="Provenance source label for this manual edit")
    mem_set.add_argument("--replace-label", help="Update first node matching this label")
    mem_set.add_argument("--commit-message", help="Optional version commit message")
    mem_set.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_set.add_argument("--format", choices=["json", "text"], default="text")

    mem_resolve = mem_sub.add_parser("resolve", help="Resolve a memory conflict")
    mem_resolve.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    mem_resolve.add_argument("--conflict-id", required=True, help="Conflict ID from memory conflicts")
    mem_resolve.add_argument(
        "--action",
        required=True,
        choices=["accept-new", "keep-old", "merge", "ignore"],
        help="Resolution action",
    )
    mem_resolve.add_argument("--commit-message", help="Optional version commit message")
    mem_resolve.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mem_resolve.add_argument("--format", choices=["json", "text"], default="text")

    # -- query (Phase 1 + Phase 5) -----------------------------------------
    qry = sub.add_parser("query", help="Query a context/graph file")
    qry.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    qry.add_argument("--node", help="Look up a node by label")
    qry.add_argument("--neighbors", help="Get neighbors of a node by label")
    qry.add_argument("--category", help="List nodes by tag/category")
    qry.add_argument("--path", nargs=2, metavar=("FROM", "TO"), help="Find shortest path between two labels")
    qry.add_argument("--changed-since", help="Show nodes changed since ISO date")
    qry.add_argument("--strongest", type=int, metavar="N", help="Top N nodes by confidence")
    qry.add_argument("--weakest", type=int, metavar="N", help="Bottom N nodes by confidence")
    qry.add_argument("--isolated", action="store_true", help="List nodes with zero edges")
    qry.add_argument("--related", nargs="?", const="", metavar="LABEL", help="Nodes related to LABEL (default depth=2)")
    qry.add_argument("--related-depth", type=int, default=2, help="Depth for --related traversal (default: 2)")
    qry.add_argument("--components", action="store_true", help="Show connected components")
    qry.add_argument("--search", metavar="QUERY", help="Hybrid search across labels, aliases, and descriptions")
    qry.add_argument("--limit", type=int, default=10, help="Result limit for --search or --dsl SEARCH (default: 10)")
    qry.add_argument("--dsl", metavar="QUERY", help="Run the Cortex query DSL directly")
    qry.add_argument("--nl", metavar="QUERY", help="Natural-language query (limited patterns)")
    qry.add_argument("--at", help="Query the graph as-of an ISO timestamp using validity windows and snapshots")
    qry.add_argument("--format", choices=["json", "text"], default="text", help="Output format (default: text)")

    # -- stats (Phase 1) ---------------------------------------------------
    st = sub.add_parser("stats", help="Show graph/context statistics")
    st.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    # -- timeline (Phase 2) ------------------------------------------------
    tl = sub.add_parser("timeline", help="Generate timeline from context/graph")
    tl.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    tl.add_argument("--from", dest="from_date", help="Start date (ISO-8601)")
    tl.add_argument("--to", dest="to_date", help="End date (ISO-8601)")
    tl.add_argument(
        "--format", "-f", dest="output_format", choices=["md", "html"], default="md", help="Output format (default: md)"
    )

    # -- contradictions (Phase 2) ------------------------------------------
    ct = sub.add_parser("contradictions", help="Detect contradictions in context/graph")
    ct.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    ct.add_argument("--severity", type=float, default=0.0, help="Minimum severity threshold (0.0-1.0)")
    ct.add_argument(
        "--type",
        dest="contradiction_type",
        choices=["negation_conflict", "temporal_flip", "source_conflict", "tag_conflict", "temporal_claim_conflict"],
        help="Filter by contradiction type",
    )
    ct.add_argument("--format", choices=["json", "text"], default="text", help="Output format (default: text)")

    # -- drift (Phase 2) ---------------------------------------------------
    dr = sub.add_parser("drift", help="Compute identity drift between two graphs")
    dr.add_argument("input_file", help="Path to first context JSON (v4 or v5)")
    dr.add_argument("--compare", required=True, help="Path to second context JSON to compare against")

    # -- diff (version history) --------------------------------------------
    df = sub.add_parser("diff", help="Compare two stored graph versions")
    df.add_argument("version_a", help="Base version ID, unique prefix, branch name, or HEAD")
    df.add_argument("version_b", help="Target version ID, unique prefix, branch name, or HEAD")
    df.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    df.add_argument("--format", choices=["json", "text"], default="text")
    df.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- blame (memory receipts) -------------------------------------------
    bl = sub.add_parser("blame", help="Explain where a memory claim came from")
    bl.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    bl_target = bl.add_mutually_exclusive_group(required=True)
    bl_target.add_argument("--label", help="Node label or alias to trace")
    bl_target.add_argument("--node-id", help="Node ID to trace")
    bl.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    bl.add_argument("--ref", default="HEAD", help="Branch/ref/version ancestry to inspect (default: HEAD)")
    bl.add_argument("--source", help="Filter receipts to a specific source label")
    bl.add_argument("--limit", type=int, default=20, help="Max versions to scan for blame history (default: 20)")
    bl.add_argument("--format", choices=["json", "text"], default="text")
    bl.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- history (receipts timeline) --------------------------------------
    hs = sub.add_parser("history", help="Show chronological memory receipts for a node")
    hs.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    hs_target = hs.add_mutually_exclusive_group(required=True)
    hs_target.add_argument("--label", help="Node label or alias to trace")
    hs_target.add_argument("--node-id", help="Node ID to trace")
    hs.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    hs.add_argument("--ref", default="HEAD", help="Branch/ref/version ancestry to inspect (default: HEAD)")
    hs.add_argument("--source", help="Filter receipts to a specific source label")
    hs.add_argument("--limit", type=int, default=20, help="Max versions to scan (default: 20)")
    hs.add_argument("--format", choices=["json", "text"], default="text")
    hs.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- claim (ledger) ----------------------------------------------------
    clm = sub.add_parser("claim", help="Inspect the local claim ledger")
    clm_sub = clm.add_subparsers(dest="claim_subcommand")

    clm_log = clm_sub.add_parser("log", help="List recent claim events")
    clm_log.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_log.add_argument("--label", help="Filter by label or alias")
    clm_log.add_argument("--node-id", help="Filter by node id")
    clm_log.add_argument("--source", help="Filter by source")
    clm_log.add_argument("--version", help="Filter by version id prefix")
    clm_log.add_argument(
        "--op", choices=["assert", "retract", "accept", "reject", "supersede"], help="Filter by operation"
    )
    clm_log.add_argument("--limit", type=int, default=20, help="Max events to return (default: 20)")
    clm_log.add_argument("--format", choices=["json", "text"], default="text")

    clm_show = clm_sub.add_parser("show", help="Show all events for a claim id")
    clm_show.add_argument("claim_id", help="Claim id")
    clm_show.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_show.add_argument("--format", choices=["json", "text"], default="text")

    clm_accept = clm_sub.add_parser("accept", help="Accept a claim and restore it into the graph if needed")
    clm_accept.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    clm_accept.add_argument("claim_id", help="Claim id")
    clm_accept.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_accept.add_argument("--commit-message", help="Optional version commit message")
    clm_accept.add_argument("--format", choices=["json", "text"], default="text")

    clm_reject = clm_sub.add_parser("reject", help="Reject a claim and remove its graph support")
    clm_reject.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    clm_reject.add_argument("claim_id", help="Claim id")
    clm_reject.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_reject.add_argument("--commit-message", help="Optional version commit message")
    clm_reject.add_argument("--format", choices=["json", "text"], default="text")

    clm_sup = clm_sub.add_parser("supersede", help="Supersede a claim with an updated claim state")
    clm_sup.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    clm_sup.add_argument("claim_id", help="Claim id")
    clm_sup.add_argument("--label", help="Override label")
    clm_sup.add_argument("--tag", action="append", dest="tags", default=[], help="Replacement tag (repeatable)")
    clm_sup.add_argument("--alias", action="append", default=[], help="Alias to keep on the superseding claim")
    clm_sup.add_argument("--status", help="Override status")
    clm_sup.add_argument("--valid-from", default="", help="Override valid_from timestamp")
    clm_sup.add_argument("--valid-to", default="", help="Override valid_to timestamp")
    clm_sup.add_argument("--confidence", type=float, help="Override confidence")
    clm_sup.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_sup.add_argument("--commit-message", help="Optional version commit message")
    clm_sup.add_argument("--format", choices=["json", "text"], default="text")

    # -- checkout (version history) ----------------------------------------
    ck = sub.add_parser("checkout", help="Write a stored graph version to a file")
    ck.add_argument("version_id", help="Version ID, unique prefix, branch name, or HEAD")
    ck.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    ck.add_argument("--output", "-o", help="Output file path (default: <version>.json)")
    ck.add_argument("--no-verify", action="store_true", help="Skip snapshot integrity verification")
    ck.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- rollback (version history) ----------------------------------------
    rb = sub.add_parser("rollback", help="Restore a prior memory state as a new commit")
    rb.add_argument("input_file", help="Path to context JSON (v4 or v5) to overwrite with the restored graph")
    rb_target = rb.add_mutually_exclusive_group(required=True)
    rb_target.add_argument("--to", dest="target_ref", help="Version ID, unique prefix, branch name, or HEAD")
    rb_target.add_argument(
        "--at", dest="target_time", help="Restore the latest version at or before this ISO timestamp"
    )
    rb.add_argument("--ref", default="HEAD", help="Restrict --at lookup to this branch/ref (default: HEAD)")
    rb.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rb.add_argument("--message", help="Optional rollback commit message")
    rb.add_argument("--format", choices=["json", "text"], default="text")
    rb.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    rb.add_argument("--approve", action="store_true", help="Explicitly approve a gated rollback")

    # -- identity (Phase 3) ------------------------------------------------
    ident = sub.add_parser("identity", help="Init/show UPAI identity")
    ident.add_argument("--init", action="store_true", help="Generate new identity")
    ident.add_argument("--name", help="Human-readable name for identity")
    ident.add_argument("--show", action="store_true", help="Show current identity")
    ident.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    ident.add_argument("--did-doc", action="store_true", help="Output W3C DID document JSON")
    ident.add_argument("--keychain", action="store_true", help="Show key rotation history and status")

    # -- commit (Phase 3) --------------------------------------------------
    cm = sub.add_parser("commit", help="Version a graph snapshot")
    cm.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    cm.add_argument("-m", "--message", required=True, help="Commit message")
    cm.add_argument("--source", default="manual", help="Source label (extraction, merge, manual)")
    cm.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    cm.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    cm.add_argument("--approve", action="store_true", help="Explicitly approve a gated commit")

    # -- branch (Git-for-AI-Memory) ---------------------------------------
    br = sub.add_parser("branch", help="List or create memory branches")
    br.add_argument("branch_name", nargs="?", help="Branch name to create")
    br.add_argument("--from", dest="from_ref", default="HEAD", help="Start point ref (default: HEAD)")
    br.add_argument("--switch", action="store_true", help="Switch to the new branch after creating it")
    br.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    br.add_argument("--format", choices=["json", "text"], default="text")
    br.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- switch (Git-for-AI-Memory) ---------------------------------------
    sw = sub.add_parser("switch", help="Switch the active memory branch or migrate context to another AI tool")
    sw.add_argument("branch_name", nargs="?", help="Branch name to switch to")
    sw.add_argument("-c", "--create", action="store_true", help="Create the branch if it does not exist")
    sw.add_argument(
        "--from", dest="from_ref", default="HEAD", help="Start point when creating a branch (default: HEAD)"
    )
    sw.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    sw.add_argument(
        "--to",
        dest="to_platform",
        choices=[
            "claude",
            "claude-code",
            "chatgpt",
            "codex",
            "copilot",
            "gemini",
            "grok",
            "hermes",
            "windsurf",
            "cursor",
        ],
        help="Portable platform switch target. When set, --from is treated as the source export/context path.",
    )
    sw.add_argument("--output", "-o", help="Output directory for generated switch artifacts")
    sw.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sw.add_argument(
        "--input-format",
        "-F",
        choices=[
            "auto",
            "openai",
            "gemini",
            "perplexity",
            "grok",
            "cursor",
            "windsurf",
            "copilot",
            "jsonl",
            "api_logs",
            "messages",
            "text",
            "generic",
        ],
        default="auto",
        help="Override input format detection when using portable switch mode",
    )
    sw.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy for portable switch mode",
    )
    sw.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    sw.add_argument("--dry-run", action="store_true", help="Preview portable switch without writing files")

    # -- merge (Git-for-AI-Memory) ----------------------------------------
    mg = sub.add_parser("merge", help="Merge another memory branch/ref into the current branch")
    mg.add_argument("ref_name", nargs="?", help="Branch or ref to merge into the current branch")
    mg.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    mg.add_argument("--message", help="Custom merge commit message")
    mg.add_argument("--dry-run", action="store_true", help="Compute merge result without committing")
    mg.add_argument("--output", "-o", help="Optional path to write the merged graph snapshot")
    mg.add_argument("--format", choices=["json", "text"], default="text")
    mg.add_argument("--conflicts", action="store_true", help="Show pending merge conflicts")
    mg.add_argument("--resolve", metavar="CONFLICT_ID", help="Resolve a pending merge conflict")
    mg.add_argument("--choose", choices=["current", "incoming"], help="Conflict resolution choice")
    mg.add_argument("--commit-resolved", action="store_true", help="Commit the current resolved merge state")
    mg.add_argument("--abort", action="store_true", help="Abort the pending merge state")
    mg.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    mg.add_argument("--approve", action="store_true", help="Explicitly approve a gated merge")

    # -- review (Git-for-AI-Memory) ---------------------------------------
    rvw = sub.add_parser("review", help="Review a memory graph against a stored ref")
    rvw.add_argument("input_file", nargs="?", help="Optional context JSON to review instead of a stored ref")
    rvw.add_argument("--against", required=True, help="Baseline branch/ref/version to compare against")
    rvw.add_argument("--ref", default="HEAD", help="Current branch/ref/version when no input file is provided")
    rvw.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rvw.add_argument(
        "--fail-on",
        default="blocking",
        help="Comma-separated review gates: blocking, contradictions, temporal_gaps, low_confidence, retractions, changes, none",
    )
    rvw.add_argument("--format", choices=["json", "text", "md"], default="text")

    # -- log (Phase 3) -----------------------------------------------------
    lg = sub.add_parser("log", help="Show version history")
    lg.add_argument("--limit", type=int, default=10, help="Max entries to show")
    lg.add_argument("--branch", help="Branch/ref to inspect (default: current branch)")
    lg.add_argument("--all", action="store_true", help="Show global history instead of branch ancestry")
    lg.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    lg.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- governance --------------------------------------------------------
    gov = sub.add_parser("governance", help="Manage access control and approval policies")
    gov_sub = gov.add_subparsers(dest="governance_subcommand")

    gov_list = gov_sub.add_parser("list", help="List governance rules")
    gov_list.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_list.add_argument("--format", choices=["json", "text"], default="text")

    gov_add = gov_sub.add_parser("allow", help="Create or replace an allow rule")
    gov_add.add_argument("name", help="Rule name")
    gov_add.add_argument("--actor", dest="actor_pattern", default="*", help="Actor glob pattern")
    gov_add.add_argument("--action", action="append", required=True, help="Action to allow (repeatable or '*')")
    gov_add.add_argument("--namespace", action="append", required=True, help="Namespace/branch glob pattern")
    gov_add.add_argument("--require-approval", action="store_true", help="Always require approval for this rule")
    gov_add.add_argument("--approval-below-confidence", type=float, help="Require approval below this confidence")
    gov_add.add_argument("--approval-tag", action="append", default=[], help="Tag that requires approval when changed")
    gov_add.add_argument(
        "--approval-change", action="append", default=[], help="Semantic change type requiring approval"
    )
    gov_add.add_argument("--description", default="", help="Optional rule description")
    gov_add.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_add.add_argument("--format", choices=["json", "text"], default="text")

    gov_deny = gov_sub.add_parser("deny", help="Create or replace a deny rule")
    gov_deny.add_argument("name", help="Rule name")
    gov_deny.add_argument("--actor", dest="actor_pattern", default="*", help="Actor glob pattern")
    gov_deny.add_argument("--action", action="append", required=True, help="Action to deny (repeatable or '*')")
    gov_deny.add_argument("--namespace", action="append", required=True, help="Namespace/branch glob pattern")
    gov_deny.add_argument("--description", default="", help="Optional rule description")
    gov_deny.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_deny.add_argument("--format", choices=["json", "text"], default="text")

    gov_rm = gov_sub.add_parser("delete", help="Delete a governance rule")
    gov_rm.add_argument("name", help="Rule name")
    gov_rm.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_rm.add_argument("--format", choices=["json", "text"], default="text")

    gov_check = gov_sub.add_parser("check", help="Check whether an actor may perform an action")
    gov_check.add_argument("--actor", required=True, help="Actor identity")
    gov_check.add_argument(
        "--action",
        required=True,
        choices=GOVERNANCE_ACTION_CHOICES,
        help="Action to evaluate",
    )
    gov_check.add_argument("--namespace", required=True, help="Namespace or branch name")
    gov_check.add_argument("--input-file", help="Optional current graph to evaluate for approval gating")
    gov_check.add_argument("--against", help="Optional baseline ref for semantic diff/approval gating")
    gov_check.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_check.add_argument("--format", choices=["json", "text"], default="text")

    # -- remote ------------------------------------------------------------
    rem = sub.add_parser("remote", help="Manage remote memory stores and sync branches")
    rem_sub = rem.add_subparsers(dest="remote_subcommand")

    rem_list = rem_sub.add_parser("list", help="List configured remotes")
    rem_list.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_list.add_argument("--format", choices=["json", "text"], default="text")

    rem_add = rem_sub.add_parser("add", help="Add or replace a remote memory store")
    rem_add.add_argument("name", help="Remote name")
    rem_add.add_argument("path", help="Path to another .cortex store or its parent directory")
    rem_add.add_argument("--default-branch", default="main", help="Default remote branch (default: main)")
    rem_add.add_argument(
        "--allow-namespace",
        action="append",
        default=[],
        help="Allowed remote namespace/branch prefix for sync operations (repeatable; default: remote default branch)",
    )
    rem_add.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_add.add_argument("--format", choices=["json", "text"], default="text")

    rem_rm = rem_sub.add_parser("remove", help="Remove a remote definition")
    rem_rm.add_argument("name", help="Remote name")
    rem_rm.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_rm.add_argument("--format", choices=["json", "text"], default="text")

    rem_push = rem_sub.add_parser("push", help="Push a memory branch to a remote store")
    rem_push.add_argument("name", help="Remote name")
    rem_push.add_argument("--branch", default="HEAD", help="Local branch/ref to push (default: HEAD)")
    rem_push.add_argument("--to-branch", help="Remote branch name (default: same as source branch)")
    rem_push.add_argument("--force", action="store_true", help="Allow non-fast-forward remote updates")
    rem_push.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_push.add_argument("--format", choices=["json", "text"], default="text")
    rem_push.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    rem_pull = rem_sub.add_parser("pull", help="Pull a remote branch into a local branch")
    rem_pull.add_argument("name", help="Remote name")
    rem_pull.add_argument("--branch", help="Remote branch to pull (default: remote default branch)")
    rem_pull.add_argument("--into-branch", help="Local branch to update (default: remotes/<name>/<branch>)")
    rem_pull.add_argument("--switch", action="store_true", help="Switch to the updated branch after pulling")
    rem_pull.add_argument("--force", action="store_true", help="Allow non-fast-forward local updates")
    rem_pull.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_pull.add_argument("--format", choices=["json", "text"], default="text")
    rem_pull.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    rem_fork = rem_sub.add_parser("fork", help="Fork a remote branch into a new local branch")
    rem_fork.add_argument("name", help="Remote name")
    rem_fork.add_argument("branch_name", help="New local branch name")
    rem_fork.add_argument("--remote-branch", help="Remote branch to fork (default: remote default branch)")
    rem_fork.add_argument("--switch", action="store_true", help="Switch to the new local branch after forking")
    rem_fork.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rem_fork.add_argument("--format", choices=["json", "text"], default="text")
    rem_fork.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

    # -- sync (Phase 3) ----------------------------------------------------
    sy = sub.add_parser("sync", help="Disclosure-filtered export or smart context propagation")
    sy.add_argument("input_file", nargs="?", help="Path to context JSON (v4 or v5)")
    sy.add_argument("--to", "-t", help="Target platform adapter (legacy mode)")
    sy.add_argument(
        "--policy",
        "-p",
        default="full",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy (default: full)",
    )
    sy.add_argument("--output", "-o", default="./output", help="Output directory")
    sy.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    sy.add_argument("--smart", action="store_true", help="Route the right context slice to each supported AI tool")
    sy.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sy.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    sy.add_argument("--format", choices=["json", "text"], default="text")

    # -- verify (Phase 3) --------------------------------------------------
    vr = sub.add_parser("verify", help="Verify a signed export")
    vr.add_argument("input_file", help="Path to signed export file")

    # -- gaps (Phase 5) ----------------------------------------------------
    gp = sub.add_parser("gaps", help="Analyze gaps in knowledge graph")
    gp.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    # -- digest (Phase 5) --------------------------------------------------
    dg = sub.add_parser("digest", help="Generate weekly digest (compare two graphs)")
    dg.add_argument("input_file", help="Path to current context JSON (v4 or v5)")
    dg.add_argument("--previous", required=True, help="Path to previous context JSON to compare against")

    # -- viz (Phase 6) -----------------------------------------------------
    vz = sub.add_parser("viz", help="Render graph visualization")
    vz.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    vz.add_argument("--output", "-o", default="graph.html", help="Output file path (default: graph.html)")
    vz.add_argument(
        "--format",
        "-f",
        dest="viz_format",
        choices=["html", "svg"],
        default="html",
        help="Output format (default: html)",
    )
    vz.add_argument("--max-nodes", type=int, default=200, help="Max nodes to render (default: 200)")
    vz.add_argument("--width", type=int, default=960, help="Width in pixels")
    vz.add_argument("--height", type=int, default=720, help="Height in pixels")
    vz.add_argument("--iterations", type=int, default=50, help="Layout iterations (default: 50)")
    vz.add_argument("--no-open", action="store_true", help="Don't open in browser after rendering")

    # -- watch (Phase 6) ---------------------------------------------------
    wa = sub.add_parser("watch", help="Monitor directory for new exports")
    wa.add_argument("watch_dir", help="Directory to monitor for export files")
    wa.add_argument("--graph", "-g", required=True, help="Path to context.json to update")
    wa.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")

    # -- sync-schedule (Phase 6) -------------------------------------------
    ss = sub.add_parser("sync-schedule", help="Run periodic platform sync")
    ss.add_argument("--config", "-c", required=True, help="Path to sync config JSON")
    ss.add_argument("--once", action="store_true", help="Run all syncs once and exit")

    # -- extract-coding (Phase 7) ------------------------------------------
    ec = sub.add_parser("extract-coding", help="Extract identity from coding sessions")
    ec.add_argument("input_file", nargs="?", help="Path to Claude Code session JSONL (omit for --discover)")
    ec.add_argument("--discover", action="store_true", help="Auto-discover Claude Code sessions from ~/.claude/")
    ec.add_argument("--project", "-p", help="Filter discovered sessions by project name substring")
    ec.add_argument("--limit", "-n", type=int, default=10, help="Max sessions to process (default: 10)")
    ec.add_argument("--output", "-o", help="Output JSON path")
    ec.add_argument("--merge", "-m", help="Existing context file to merge results into")
    ec.add_argument("--verbose", "-v", action="store_true")
    ec.add_argument("--stats", action="store_true", help="Print session statistics")
    ec.add_argument("--enrich", action="store_true", help="Read project files (README, manifests) to enrich extraction")
    ec.add_argument(
        "--watch", "-w", action="store_true", help="Watch for new/modified sessions and continuously extract"
    )
    ec.add_argument("--interval", type=int, default=10, help="Watch poll interval in seconds (default: 10)")
    ec.add_argument(
        "--settle", type=float, default=5.0, help="Debounce: seconds to wait after last file write (default: 5)"
    )
    ec.add_argument(
        "--context-refresh",
        nargs="*",
        default=None,
        help="Auto-refresh context for platforms on update (e.g., --context-refresh claude-code cursor)",
    )
    ec.add_argument(
        "--context-policy",
        default=None,
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy for context refresh",
    )

    # -- context-hook (auto-inject) -------------------------------------------
    ch = sub.add_parser("context-hook", help="Install/manage Cortex context hook for Claude Code")
    ch.add_argument("action", choices=["install", "uninstall", "test", "status"], help="Hook action to perform")
    ch.add_argument("graph_file", nargs="?", help="Path to Cortex graph JSON (required for install)")
    ch.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy (default: technical)",
    )
    ch.add_argument("--max-chars", type=int, default=1500, help="Max characters for injected context (default: 1500)")

    # -- context-export (one-shot compact export) ------------------------------
    ce = sub.add_parser("context-export", help="Export compact context markdown to stdout")
    ce.add_argument("input_file", help="Path to Cortex graph JSON")
    ce.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy (default: technical)",
    )
    ce.add_argument("--max-chars", type=int, default=1500, help="Max characters (default: 1500)")

    # -- context-write (cross-platform context files) -------------------------
    cw = sub.add_parser("context-write", help="Write identity context to AI coding tool config files")
    cw.add_argument("input_file", help="Path to Cortex graph JSON")
    cw.add_argument(
        "--platforms",
        "-p",
        nargs="+",
        default=["claude-code"],
        help="Target platforms: claude-code, claude-code-project, codex, cursor, "
        "copilot, windsurf, gemini or gemini-cli, or 'all' (default: claude-code)",
    )
    cw.add_argument("--project", "-d", help="Project directory for per-project files (default: cwd)")
    cw.add_argument(
        "--policy",
        default=None,
        choices=list(BUILTIN_POLICIES.keys()),
        help="Override disclosure policy for all platforms",
    )
    cw.add_argument("--max-chars", type=int, default=1500, help="Max characters per context (default: 1500)")
    cw.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    cw.add_argument("--watch", action="store_true", help="Watch graph file and auto-refresh on change")
    cw.add_argument("--interval", type=int, default=30, help="Watch poll interval in seconds (default: 30)")

    # -- portable (one-command cross-tool context) -------------------------
    pt = sub.add_parser(
        "portable",
        help="Compatibility command for legacy portability-first context sync",
        description="Compatibility command for legacy portability-first context sync.",
    )
    pt.add_argument("input_file", nargs="?", help="Path to a chat export or existing Cortex context graph")
    pt.add_argument(
        "--to",
        "-t",
        nargs="+",
        default=["all"],
        help="Targets: claude, claude-code, chatgpt, codex, copilot, gemini, grok, hermes, windsurf, cursor, or all",
    )
    pt.add_argument("--output", "-o", default="./portable", help="Output directory for context and generated artifacts")
    pt.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    pt.add_argument(
        "--input-format",
        "-F",
        choices=[
            "auto",
            "openai",
            "gemini",
            "perplexity",
            "grok",
            "cursor",
            "windsurf",
            "copilot",
            "jsonl",
            "api_logs",
            "messages",
            "text",
            "generic",
        ],
        default="auto",
        help="Override input format auto-detection for export inputs",
    )
    pt.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy for installed context and Claude artifacts",
    )
    pt.add_argument("--confidence", "-c", choices=["high", "medium", "low", "all"], default="medium")
    pt.add_argument("--max-chars", type=int, default=1500, help="Max characters per installed context file")
    pt.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    pt.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    pt.add_argument("--verbose", "-v", action="store_true")
    pt.add_argument("--redact", action="store_true", help="Enable PII redaction when extracting raw exports")
    pt.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    pt.add_argument(
        "--from-detected",
        nargs="+",
        help="Explicitly adopt detected local platform sources instead of a raw export file",
    )
    pt.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for detected exports (repeatable)",
    )
    pt.add_argument(
        "--include-config-metadata",
        action="store_true",
        help="Also ingest detected MCP config metadata; config files are metadata-only by default",
    )
    pt.add_argument(
        "--include-unmanaged-text",
        action="store_true",
        help="Also ingest unmanaged text outside Cortex markers from detected instruction files",
    )
    pt.add_argument(
        "--no-redact-detected",
        action="store_true",
        help="Disable the default PII redaction applied to detected local source adoption",
    )
    pt.add_argument("--format", choices=["json", "text"], default="text")

    scn = sub.add_parser(
        "scan",
        help="Operational command to inspect runtime context coverage",
        description="Operational command to inspect runtime context coverage.",
    )
    scn.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    scn.add_argument("--project", "-d", help="Project directory to inspect (default: cwd)")
    scn.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for chat exports or tool artifacts (repeatable)",
    )
    scn.add_argument("--format", choices=["json", "text"], default="text")

    rem = sub.add_parser(
        "remember",
        help="Compatibility command for portability-style remember-and-propagate",
        description="Compatibility command for portability-style remember-and-propagate.",
    )
    rem.add_argument("statement", help="Plain-language fact or preference to remember")
    rem.add_argument(
        "--to",
        "-t",
        nargs="+",
        default=["all"],
        help="Targets to update after remembering (default: all supported portability targets)",
    )
    rem.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    rem.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    rem.add_argument("--smart", action="store_true", help="Use smart per-tool routing when propagating")
    rem.add_argument(
        "--policy",
        default="full",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy when propagating remembered context",
    )
    rem.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    rem.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    rem.add_argument("--format", choices=["json", "text"], default="text")

    sts = sub.add_parser(
        "status",
        help="Operational command to inspect stale or missing runtime context",
        description="Operational command to inspect stale or missing runtime context.",
    )
    sts.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    sts.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sts.add_argument("--format", choices=["json", "text"], default="text")

    bld = sub.add_parser(
        "build",
        help="Compatibility command for legacy digital-footprint imports",
        description="Compatibility command for legacy digital-footprint imports.",
    )
    bld.add_argument(
        "--from",
        dest="sources",
        action="append",
        required=True,
        help="Source to build from: github, resume, package.json, git-history",
    )
    bld.add_argument("inputs", nargs="*", help="Optional input paths consumed by sources like resume")
    bld.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    bld.add_argument("--project", "-d", help="Project directory for manifests and git history (default: cwd)")
    bld.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra root to search for GitHub repos when using --from github",
    )
    bld.add_argument("--sync", action="store_true", help="Propagate the built context immediately after import")
    bld.add_argument(
        "--to",
        "-t",
        nargs="+",
        default=["claude-code", "codex", "cursor", "copilot", "windsurf", "gemini"],
        help="Targets to update when --sync is enabled",
    )
    bld.add_argument("--smart", action="store_true", help="Use smart per-tool routing when syncing")
    bld.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy when syncing after build",
    )
    bld.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    bld.add_argument("--format", choices=["json", "text"], default="text")

    aud = sub.add_parser(
        "audit",
        help="Compatibility command for legacy portability drift diagnostics",
        description="Compatibility command for legacy portability drift diagnostics.",
    )
    aud.add_argument("--store-dir", default=".cortex", help="Portability state directory (default: .cortex)")
    aud.add_argument("--project", "-d", help="Project directory for live manifest comparison (default: cwd)")
    aud.add_argument("--format", choices=["json", "text"], default="text")

    # -- mind (top-level portable minds) ----------------------------------
    mind = sub.add_parser(
        "mind",
        help="Manage Cortex Minds: portable, versioned, composable agent minds",
        description="Manage Cortex Minds: durable identity, memory, composition, and mounts.",
        epilog=MIND_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mind_sub = mind.add_subparsers(dest="mind_subcommand")

    mind_init = mind_sub.add_parser("init", help="Create a new Cortex Mind")
    mind_init.add_argument("name", help="Mind id")
    mind_init.add_argument(
        "--kind",
        choices=["person", "agent", "project", "team"],
        default="person",
        help="Mind kind (default: person)",
    )
    mind_init.add_argument("--label", default="", help="Display label for the Mind")
    mind_init.add_argument("--owner", default="", help="Owner label recorded in the manifest")
    mind_init.add_argument(
        "--default-policy",
        default="professional",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Default disclosure policy for the Mind",
    )
    mind_init.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_init.add_argument("--format", choices=["json", "text"], default="text")

    mind_list = mind_sub.add_parser("list", help="List local Cortex Minds")
    mind_list.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_list.add_argument("--format", choices=["json", "text"], default="text")

    mind_status = mind_sub.add_parser("status", help="Show Cortex Mind status")
    mind_status.add_argument("name", help="Mind id")
    mind_status.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_status.add_argument("--format", choices=["json", "text"], default="text")

    mind_default = mind_sub.add_parser("default", help="Show, set, or clear the default Cortex Mind")
    mind_default.add_argument("name", nargs="?", help="Mind id to set as the default")
    mind_default.add_argument("--clear", action="store_true", help="Clear the configured default Mind")
    mind_default.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_default.add_argument("--format", choices=["json", "text"], default="text")

    mind_ingest = mind_sub.add_parser("ingest", help="Queue detected local context for review on a Cortex Mind")
    mind_ingest.add_argument("name", help="Mind id")
    mind_ingest.add_argument(
        "--from-detected",
        nargs="+",
        required=True,
        help="Queue detected local platform sources as a review proposal for the Mind",
    )
    mind_ingest.add_argument("--project", "-d", help="Project directory for detected local sources (default: cwd)")
    mind_ingest.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Extra directory to search for detected exports (repeatable)",
    )
    mind_ingest.add_argument(
        "--include-config-metadata",
        action="store_true",
        help="Also ingest detected MCP config metadata; config files are metadata-only by default",
    )
    mind_ingest.add_argument(
        "--include-unmanaged-text",
        action="store_true",
        help="Also ingest unmanaged text outside Cortex markers from detected instruction files",
    )
    mind_ingest.add_argument("--redact", action="store_true", help="Enable PII redaction for detected local sources")
    mind_ingest.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    mind_ingest.add_argument(
        "--no-redact-detected",
        action="store_true",
        help="Disable the default PII redaction applied to detected local source adoption",
    )
    mind_ingest.add_argument(
        "--message",
        default="",
        help="Optional commit message for the Mind graph update",
    )
    mind_ingest.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_ingest.add_argument("--format", choices=["json", "text"], default="text")

    mind_remember = mind_sub.add_parser("remember", help="Teach a Cortex Mind one new fact or preference directly")
    mind_remember.add_argument("name", help="Mind id")
    mind_remember.add_argument("statement", help="Plain-language fact or preference to add to the Mind")
    mind_remember.add_argument(
        "--message",
        default="",
        help="Optional commit message for the Mind graph update",
    )
    mind_remember.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_remember.add_argument("--format", choices=["json", "text"], default="text")

    mind_attach = mind_sub.add_parser("attach-pack", help="Attach an existing Brainpack to a Cortex Mind")
    mind_attach.add_argument("name", help="Mind id")
    mind_attach.add_argument("pack", help="Brainpack name")
    mind_attach.add_argument("--priority", type=int, default=100, help="Composition priority for the attachment")
    mind_attach.add_argument(
        "--always-on", action="store_true", help="Always include this Brainpack during composition"
    )
    mind_attach.add_argument(
        "--target",
        action="append",
        default=[],
        help="Optional target filter for this Brainpack attachment. Repeat for multiple targets.",
    )
    mind_attach.add_argument(
        "--task-term",
        action="append",
        default=[],
        help="Optional task-term activator for this Brainpack attachment. Repeat for multiple terms.",
    )
    mind_attach.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_attach.add_argument("--format", choices=["json", "text"], default="text")

    mind_detach = mind_sub.add_parser("detach-pack", help="Detach a Brainpack from a Cortex Mind")
    mind_detach.add_argument("name", help="Mind id")
    mind_detach.add_argument("pack", help="Brainpack name")
    mind_detach.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_detach.add_argument("--format", choices=["json", "text"], default="text")

    mind_compose = mind_sub.add_parser("compose", help="Compose a target-aware runtime slice from a Cortex Mind")
    mind_compose.add_argument("name", help="Mind id")
    mind_compose.add_argument(
        "--to", required=True, help="Target tool such as hermes, openclaw, codex, cursor, claude-code, or chatgpt"
    )
    mind_compose.add_argument("--task", default="", help="Optional task hint used to activate attached Brainpacks")
    mind_compose.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    mind_compose.add_argument("--smart", action="store_true", help="Use smart routing for the target")
    mind_compose.add_argument(
        "--policy",
        default="",
        choices=[""] + list(BUILTIN_POLICIES.keys()),
        help="Optional disclosure policy override",
    )
    mind_compose.add_argument("--max-chars", type=int, default=1500, help="Max characters in the rendered context")
    mind_compose.add_argument(
        "--activation-target",
        default="",
        help="Optional runtime target used only for Brainpack activation selection (for example: openclaw)",
    )
    mind_compose.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_compose.add_argument("--format", choices=["json", "text"], default="text")

    mind_mount = mind_sub.add_parser("mount", help="Mount a Cortex Mind into supported runtimes and tools")
    mind_mount.add_argument("name", help="Mind id")
    mind_mount.add_argument(
        "--to",
        nargs="+",
        required=True,
        choices=["claude-code", "codex", "cursor", "hermes", "openclaw"],
        help="Mount target(s)",
    )
    mind_mount.add_argument("--task", default="", help="Optional task hint used during Mind composition")
    mind_mount.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_mount.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    mind_mount.add_argument("--smart", action="store_true", help="Use smart routing when mounting")
    mind_mount.add_argument(
        "--policy",
        default="",
        choices=[""] + list(BUILTIN_POLICIES.keys()),
        help="Optional disclosure policy override",
    )
    mind_mount.add_argument("--max-chars", type=int, default=1500, help="Max characters per mounted context slice")
    mind_mount.add_argument(
        "--openclaw-store-dir",
        default="",
        help="Optional OpenClaw Cortex store dir if the plugin does not use ~/.openclaw/cortex",
    )
    mind_mount.add_argument("--format", choices=["json", "text"], default="text")

    mind_mounts = mind_sub.add_parser("mounts", help="List persisted mount records for a Cortex Mind")
    mind_mounts.add_argument("name", help="Mind id")
    mind_mounts.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    mind_mounts.add_argument("--format", choices=["json", "text"], default="text")

    # -- pack (Brainpacks) -------------------------------------------------
    pk = sub.add_parser(
        "pack",
        help="Manage Brainpacks: portable, mountable domain minds",
        description="Manage Brainpacks: reusable specialist knowledge that can attach to a Mind.",
        epilog=PACK_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pk_sub = pk.add_subparsers(dest="pack_subcommand")

    pk_init = pk_sub.add_parser("init", help="Create a new Brainpack skeleton")
    pk_init.add_argument("name", help="Brainpack name")
    pk_init.add_argument("--description", default="", help="Short pack description")
    pk_init.add_argument("--owner", default="", help="Owner name recorded in the manifest")
    pk_init.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_init.add_argument("--format", choices=["json", "text"], default="text")

    pk_list = pk_sub.add_parser("list", help="List local Brainpacks")
    pk_list.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_list.add_argument("--format", choices=["json", "text"], default="text")

    pk_ingest = pk_sub.add_parser("ingest", help="Ingest raw files or folders into a Brainpack")
    pk_ingest.add_argument("name", help="Brainpack name")
    pk_ingest.add_argument("paths", nargs="+", help="File or directory paths to ingest")
    pk_ingest.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_ingest.add_argument("--copy", dest="mode", action="store_const", const="copy", default="copy")
    pk_ingest.add_argument("--reference", dest="mode", action="store_const", const="reference")
    pk_ingest.add_argument(
        "--type",
        dest="source_type",
        choices=["auto", "article", "paper", "repo", "dataset", "image", "transcript", "note"],
        default="auto",
        help="Override source type classification",
    )
    pk_ingest.add_argument("--recurse", action="store_true", help="Recurse into directories")
    pk_ingest.add_argument("--format", choices=["json", "text"], default="text")

    pk_compile = pk_sub.add_parser("compile", help="Compile a Brainpack into wiki, graph, claims, and unknowns")
    pk_compile.add_argument("name", help="Brainpack name")
    pk_compile.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_compile.add_argument("--incremental", action="store_true", help="Record this compile as incremental")
    pk_compile.add_argument("--suggest-questions", action="store_true", help="Suggest follow-up unknowns")
    pk_compile.add_argument("--max-summary-chars", type=int, default=1200, help="Summary length cap")
    pk_compile.add_argument("--format", choices=["json", "text"], default="text")

    pk_status = pk_sub.add_parser("status", help="Show Brainpack status")
    pk_status.add_argument("name", help="Brainpack name")
    pk_status.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_status.add_argument("--format", choices=["json", "text"], default="text")

    pk_context = pk_sub.add_parser("context", help="Render a routed context slice from a compiled Brainpack")
    pk_context.add_argument("name", help="Brainpack name")
    pk_context.add_argument("--target", required=True, help="Target tool such as hermes, codex, cursor, or chatgpt")
    pk_context.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_context.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    pk_context.add_argument("--smart", action="store_true", help="Use smart routing for the target")
    pk_context.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy when smart routing is disabled",
    )
    pk_context.add_argument("--max-chars", type=int, default=1500, help="Max characters in the rendered context")
    pk_context.add_argument("--format", choices=["json", "text"], default="text")

    pk_mount = pk_sub.add_parser("mount", help="Mount a compiled Brainpack directly into AI runtimes and tools")
    pk_mount.add_argument("name", help="Brainpack name")
    pk_mount.add_argument(
        "--to",
        nargs="+",
        required=True,
        choices=[
            "claude",
            "claude-code",
            "chatgpt",
            "codex",
            "copilot",
            "cursor",
            "gemini",
            "grok",
            "hermes",
            "windsurf",
            "openclaw",
        ],
        help="Mount target(s)",
    )
    pk_mount.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_mount.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    pk_mount.add_argument("--smart", action="store_true", help="Use smart routing when mounting")
    pk_mount.add_argument(
        "--policy",
        default="technical",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy when smart routing is disabled",
    )
    pk_mount.add_argument("--max-chars", type=int, default=1500, help="Max characters per mounted context slice")
    pk_mount.add_argument(
        "--openclaw-store-dir",
        default="",
        help="Optional OpenClaw Cortex store dir if the plugin does not use ~/.openclaw/cortex",
    )
    pk_mount.add_argument("--format", choices=["json", "text"], default="text")

    pk_query = pk_sub.add_parser(
        "query", help="Search a compiled Brainpack across concepts, claims, wiki, and artifacts"
    )
    pk_query.add_argument("name", help="Brainpack name")
    pk_query.add_argument("query", help="Question or search query")
    pk_query.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_query.add_argument(
        "--mode",
        choices=["hybrid", "concepts", "claims", "wiki", "unknowns", "artifacts"],
        default="hybrid",
        help="Limit the search to a specific slice of the pack",
    )
    pk_query.add_argument("--limit", type=int, default=8, help="Maximum number of ranked results")
    pk_query.add_argument("--format", choices=["json", "text"], default="text")

    pk_ask = pk_sub.add_parser(
        "ask", help="Answer a question against a Brainpack and write the result back as an artifact"
    )
    pk_ask.add_argument("name", help="Brainpack name")
    pk_ask.add_argument("question", help="Question to answer")
    pk_ask.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_ask.add_argument("--output", choices=["note", "report", "slides"], default="note", help="Artifact format")
    pk_ask.add_argument("--limit", type=int, default=8, help="Maximum number of supporting ranked results to use")
    pk_ask.add_argument(
        "--no-write-back",
        dest="write_back",
        action="store_false",
        help="Return the generated answer without saving an artifact",
    )
    pk_ask.set_defaults(write_back=True)
    pk_ask.add_argument("--format", choices=["json", "text"], default="text")

    pk_lint = pk_sub.add_parser("lint", help="Run integrity checks over a compiled Brainpack")
    pk_lint.add_argument("name", help="Brainpack name")
    pk_lint.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_lint.add_argument("--stale-days", type=int, default=30, help="Days before a concept is considered stale")
    pk_lint.add_argument(
        "--duplicate-threshold",
        type=float,
        default=0.88,
        help="Similarity threshold for duplicate concept candidates",
    )
    pk_lint.add_argument(
        "--weak-claim-confidence",
        type=float,
        default=0.65,
        help="Confidence threshold below which claims are flagged as weak",
    )
    pk_lint.add_argument(
        "--thin-article-chars",
        type=int,
        default=220,
        help="Minimum source article size before the page is considered thin",
    )
    pk_lint.add_argument("--format", choices=["json", "text"], default="text")

    pk_export = pk_sub.add_parser("export", help="Export a Brainpack as a portable bundle archive")
    pk_export.add_argument("name", help="Brainpack name")
    pk_export.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_export.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output bundle path or directory (for example ./dist/ai-memory.brainpack.zip)",
    )
    pk_export.add_argument("--no-verify", action="store_true", help="Skip post-write bundle verification")
    pk_export.add_argument("--format", choices=["json", "text"], default="text")

    pk_import = pk_sub.add_parser("import", help="Import a Brainpack bundle archive into the local store")
    pk_import.add_argument("archive", help="Path to the Brainpack bundle archive")
    pk_import.add_argument("--store-dir", default=".cortex", help="Store directory (default: .cortex)")
    pk_import.add_argument("--as", dest="as_name", default="", help="Optional new pack name for the imported bundle")
    pk_import.add_argument("--format", choices=["json", "text"], default="text")

    # -- ui (local web interface) -----------------------------------------
    ui = sub.add_parser(
        "ui",
        help="Compatibility alias for `cortex serve ui`",
        description="Compatibility alias for `cortex serve ui`.",
    )
    ui.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    ui.add_argument("--context-file", help="Default context graph file to prefill in the UI")
    ui.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    ui.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1)")
    ui.add_argument("--port", type=int, default=None, help="Bind port (default: 8765, or 0 for any free port)")
    _add_runtime_security_args(ui)
    ui.add_argument("--open", action="store_true", help="Open the UI in your browser automatically")
    ui.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    ui.add_argument("--format", choices=["json", "text"], default="text")

    # -- openapi (contract export) ----------------------------------------
    oa = sub.add_parser("openapi", help="Write the Cortex OpenAPI contract")
    oa.add_argument("--output", "-o", default="openapi/cortex-api-v1.json", help="Output path for the OpenAPI JSON")
    oa.add_argument("--server-url", help="Optional server URL to include in the contract")
    oa.add_argument("--compat-output", help="Optional output path for the API compatibility snapshot JSON")

    # -- release-notes (release metadata export) --------------------------
    rn = sub.add_parser("release-notes", help="Write release notes and a release manifest")
    rn.add_argument("--output", "-o", default="dist/release-notes.md", help="Output path for the Markdown notes")
    rn.add_argument(
        "--manifest-output",
        default="dist/release-manifest.json",
        help="Output path for the JSON release manifest",
    )
    rn.add_argument("--tag", help="Optional git tag or release label to include in the notes")
    rn.add_argument("--commit-sha", help="Optional commit SHA to include in the notes")

    # -- benchmark (release soak harness) ---------------------------------
    bench = sub.add_parser("benchmark", help="Run the lightweight self-host benchmark harness")
    bench.add_argument(
        "--store-dir", default=".cortex-bench", help="Benchmark store directory (default: .cortex-bench)"
    )
    bench.add_argument("--iterations", type=int, default=3, help="Number of benchmark iterations (default: 3)")
    bench.add_argument("--nodes", type=int, default=24, help="Nodes per generated graph (default: 24)")
    bench.add_argument("--output", "-o", help="Optional JSON output path")

    # -- server (local REST API) -----------------------------------------
    srv = sub.add_parser(
        "server",
        help="Compatibility alias for `cortex serve api`",
        description="Compatibility alias for `cortex serve api`.",
    )
    srv.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    srv.add_argument("--context-file", help="Optional default context graph file")
    srv.add_argument("--host", default=None, help="Bind host (default from config or 127.0.0.1)")
    srv.add_argument("--port", type=int, default=None, help="Bind port (default from config or 8766)")
    _add_runtime_security_args(srv)
    srv.add_argument("--api-key", help="Optional API key required for requests")
    srv.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    srv.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    srv.add_argument("--format", choices=["json", "text"], default="text")

    # -- mcp (local Model Context Protocol server) -----------------------
    mcp = sub.add_parser(
        "mcp",
        help="Compatibility alias for `cortex serve mcp`",
        description="Compatibility alias for `cortex serve mcp`.",
    )
    mcp.add_argument("--store-dir", default=None, help="Storage directory (default from config or .cortex)")
    mcp.add_argument("--context-file", help="Optional default context graph file")
    mcp.add_argument(
        "--namespace",
        help="Optional namespace prefix to pin the MCP session to, such as 'team' or 'team/atlas'",
    )
    mcp.add_argument("--config", help="Path to shared Cortex self-host config.toml")
    mcp.add_argument("--check", action="store_true", help="Print startup diagnostics and exit")
    mcp.add_argument("--format", choices=["json", "text"], default="text")

    # -- backup (export / verify / restore) ------------------------------
    bk = sub.add_parser("backup", help="Backup, verify, and restore a Cortex store")
    bk_sub = bk.add_subparsers(dest="backup_subcommand")

    bk_export = bk_sub.add_parser("export", help="Export the store into a verified backup archive")
    bk_export.add_argument("--store-dir", default=".cortex", help="Storage directory to archive (default: .cortex)")
    bk_export.add_argument("--output", "-o", help="Output archive path (default: backups/<timestamp>.zip)")
    bk_export.add_argument("--no-verify", action="store_true", help="Skip post-write archive verification")

    bk_verify = bk_sub.add_parser("verify", help="Verify a Cortex backup archive")
    bk_verify.add_argument("archive", help="Path to the backup archive")

    bk_restore = bk_sub.add_parser("restore", help="Restore a backup archive into a store directory")
    bk_restore.add_argument("archive", help="Path to the backup archive")
    bk_restore.add_argument("--store-dir", default=".cortex", help="Target storage directory (default: .cortex)")
    bk_restore.add_argument("--force", action="store_true", help="Overwrite a non-empty target directory")
    bk_restore.add_argument("--skip-verify", action="store_true", help="Skip archive verification before restore")

    bk_import = bk_sub.add_parser("import", help="Alias of backup restore")
    bk_import.add_argument("archive", help="Path to the backup archive")
    bk_import.add_argument("--store-dir", default=".cortex", help="Target storage directory (default: .cortex)")
    bk_import.add_argument("--force", action="store_true", help="Overwrite a non-empty target directory")
    bk_import.add_argument("--skip-verify", action="store_true", help="Skip archive verification before restore")

    # -- pull (import from platform export) --------------------------------
    pl = sub.add_parser("pull", help="Import a platform export file back into a graph")
    pl.add_argument("input_file", help="Path to platform export file (.json, .md, .html)")
    pl.add_argument(
        "--from",
        dest="from_platform",
        required=True,
        choices=["notion", "gdocs", "claude", "system-prompt"],
        help="Source platform adapter",
    )
    pl.add_argument("--output", "-o", default=None, help="Output graph JSON path (default: <input>_graph.json)")

    # -- completion (shell autocomplete) ------------------------------------
    cp = sub.add_parser("completion", help="Generate shell completion script")
    cp.add_argument(
        "--shell", "-s", required=True, choices=["bash", "zsh", "fish"], help="Shell type (bash, zsh, fish)"
    )

    # -- rotate (key rotation) ---------------------------------------------
    ro = sub.add_parser("rotate", help="Rotate UPAI identity key")
    ro.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    ro.add_argument(
        "--reason",
        default="rotated",
        choices=["rotated", "compromised", "expired"],
        help="Rotation reason (default: rotated)",
    )

    return parser


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
    """Disclosure-filtered export via platform adapters or smart portability sync."""
    if getattr(args, "smart", False):
        from cortex.minds import resolve_default_mind, sync_mind_compatibility_targets
        from cortex.portable_runtime import (
            ALL_PORTABLE_TARGETS,
            default_output_dir,
            load_canonical_graph,
            load_portability_state,
            sync_targets,
        )

        store_dir = Path(args.store_dir)
        try:
            default_mind = resolve_default_mind(store_dir)
        except (FileNotFoundError, ValueError) as exc:
            return _error(str(exc))
        if default_mind:
            project_dir = Path(args.project) if args.project else Path.cwd()
            try:
                payload = sync_mind_compatibility_targets(
                    store_dir,
                    default_mind,
                    targets=ALL_PORTABLE_TARGETS,
                    project_dir=project_dir,
                    smart=True,
                    policy_name=args.policy,
                    max_chars=args.max_chars,
                )
            except (FileNotFoundError, ValueError) as exc:
                return _error(str(exc))
            if _emit_result(payload, args.format) == 0:
                return 0
            _echo(f"Smart context sync complete via default Mind `{default_mind}`:")
            for target in payload["targets"]:
                label = target["target"]
                _echo(f"  {label:<12} → {', '.join(target['route_tags']) or 'default route'}")
            return 0

        state = load_portability_state(store_dir)
        graph, graph_path = load_canonical_graph(store_dir, state)
        if not graph.nodes:
            return _no_context_error()
        project_dir = (
            Path(args.project) if args.project else Path(state.project_dir) if state.project_dir else Path.cwd()
        )
        output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
        try:
            payload = sync_targets(
                graph,
                targets=ALL_PORTABLE_TARGETS,
                store_dir=store_dir,
                project_dir=str(project_dir),
                output_dir=output_dir,
                graph_path=graph_path,
                policy_name=args.policy,
                smart=True,
                max_chars=args.max_chars,
                state=state,
            )
        except PermissionError:
            return _permission_error(output_dir, action="write synced portability files")
        except OSError as exc:
            return _error(f"Could not sync portability files into {output_dir}: {exc}")
        if _emit_result(payload, args.format) == 0:
            return 0
        _echo("Smart context sync complete:")
        for target in payload["targets"]:
            label = target["target"]
            _echo(f"  {label:<12} → {', '.join(target['route_tags']) or 'default route'}")
        return 0

    input_path = Path(args.input_file)
    if not input_path.exists():
        return _missing_path_error(input_path, label="Context file")

    if not args.to:
        return _error("Specify --to for adapter export mode, or use --smart.")
    if args.to not in ADAPTERS:
        return _error(f"Unknown adapter target: {args.to}")

    graph = _load_graph(input_path)
    adapter = ADAPTERS[args.to]
    policy = BUILTIN_POLICIES[args.policy]
    output_dir = Path(args.output)

    # Load identity if available
    identity = None
    store_dir = Path(args.store_dir)
    id_path = store_dir / "identity.json"
    if id_path.exists():
        from cortex.upai.identity import UPAIIdentity

        identity = UPAIIdentity.load(store_dir)

    paths = adapter.push(graph, policy, identity=identity, output_dir=output_dir)

    if _CLI_QUIET:
        return 0
    _echo(f"Synced to {args.to} with policy '{args.policy}':")
    for p in paths:
        _echo(f"  {p}")
    return 0


def run_verify(args):
    """Verify a signed export file."""
    from cortex.upai.identity import UPAIIdentity

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {input_path}: {e}")
        return 1

    if not isinstance(data, dict) or "upai_identity" not in data:
        print("Not a UPAI-signed file (no upai_identity block).")
        return 1

    # Check integrity hash
    payload = json.dumps(data["data"], sort_keys=True, ensure_ascii=False).encode("utf-8")
    import hashlib

    computed_hash = hashlib.sha256(payload).hexdigest()
    stored_hash = data.get("integrity_hash", "")

    if computed_hash == stored_hash:
        print("Integrity: PASS (SHA-256 matches)")
    else:
        print("Integrity: FAIL (SHA-256 mismatch)")
        return 1

    # Attempt signature verification
    pub_key = data["upai_identity"].get("public_key_b64", "")
    sig = data.get("signature", "")
    did = data["upai_identity"].get("did", "")

    if did.startswith("did:upai:ed25519:") and sig:
        result = UPAIIdentity.verify(payload, sig, pub_key)
        if result:
            print("Signature: PASS (Ed25519 verified)")
        else:
            print("Signature: FAIL (Ed25519 verification failed)")
            return 1
    elif sig:
        print("Signature: HMAC (requires local secret for verification)")
    else:
        print("Signature: none")

    print(f"Identity: {did}")
    print(f"Name: {data['upai_identity'].get('name', 'unknown')}")
    return 0


def run_gaps(args):
    """Analyze gaps in the knowledge graph."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    from cortex.intelligence import GapAnalyzer

    graph = _load_graph(input_path)
    analyzer = GapAnalyzer()
    gaps = analyzer.all_gaps(graph)

    if gaps["category_gaps"]:
        print(f"Missing categories ({len(gaps['category_gaps'])}):")
        for g in gaps["category_gaps"]:
            print(f"  - {g['category']}")

    if gaps["confidence_gaps"]:
        print(f"\nLow-confidence priorities ({len(gaps['confidence_gaps'])}):")
        for g in gaps["confidence_gaps"]:
            print(f"  - {g['label']} (conf={g['confidence']:.2f})")

    if gaps["relationship_gaps"]:
        print(f"\nUnconnected groups ({len(gaps['relationship_gaps'])}):")
        for g in gaps["relationship_gaps"]:
            print(f"  - {g['tag']}: {g['node_count']} nodes, 0 edges")

    if gaps["temporal_gaps"]:
        print(f"\nTemporal gaps ({len(gaps['temporal_gaps'])}):")
        for g in gaps["temporal_gaps"]:
            print(f"  - {g['label']}: {g['kind']}" + (f" [{g['status']}]" if g.get("status") else ""))

    if gaps["isolated_nodes"]:
        print(f"\nIsolated nodes ({len(gaps['isolated_nodes'])}):")
        for g in gaps["isolated_nodes"]:
            print(f"  - {g['label']} (conf={g['confidence']:.2f})")

    if gaps["stale_nodes"]:
        print(f"\nStale nodes ({len(gaps['stale_nodes'])}):")
        for g in gaps["stale_nodes"]:
            print(f"  - {g['label']} (last seen: {g['last_seen']})")

    total = (
        len(gaps["category_gaps"])
        + len(gaps["confidence_gaps"])
        + len(gaps["relationship_gaps"])
        + len(gaps["temporal_gaps"])
        + len(gaps["isolated_nodes"])
        + len(gaps["stale_nodes"])
    )
    if total == 0:
        print("No gaps detected.")
    return 0


def run_digest(args):
    """Generate weekly digest comparing two graph snapshots."""
    input_path = Path(args.input_file)
    previous_path = Path(args.previous)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    if not previous_path.exists():
        print(f"File not found: {previous_path}")
        return 1

    from cortex.intelligence import InsightGenerator

    current = _load_graph(input_path)
    previous = _load_graph(previous_path)
    gen = InsightGenerator()
    digest = gen.digest(current=current, previous=previous)

    if digest["new_nodes"]:
        print(f"New nodes ({len(digest['new_nodes'])}):")
        for n in digest["new_nodes"]:
            print(f"  + {n['label']} (conf={n['confidence']:.2f})")

    if digest["removed_nodes"]:
        print(f"\nRemoved nodes ({len(digest['removed_nodes'])}):")
        for n in digest["removed_nodes"]:
            print(f"  - {n['label']}")

    if digest["confidence_changes"]:
        print(f"\nConfidence changes ({len(digest['confidence_changes'])}):")
        for c in digest["confidence_changes"]:
            direction = "+" if c["delta"] > 0 else ""
            print(f"  {c['label']}: {c['previous']:.2f} -> {c['current']:.2f} ({direction}{c['delta']:.2f})")

    if digest["temporal_changes"]:
        print(f"\nTemporal changes ({len(digest['temporal_changes'])}):")
        for c in digest["temporal_changes"]:
            print(
                f"  {c['label']}: "
                f"status {c['previous_status'] or '?'} -> {c['current_status'] or '?'}; "
                f"valid_from {c['previous_valid_from'] or '?'} -> {c['current_valid_from'] or '?'}; "
                f"valid_to {c['previous_valid_to'] or '?'} -> {c['current_valid_to'] or '?'}"
            )

    if digest["new_edges"]:
        print(f"\nNew edges ({len(digest['new_edges'])}):")
        for e in digest["new_edges"]:
            print(f"  {e['source']} --[{e['relation']}]--> {e['target']}")

    ds = digest["drift_score"]
    if ds.get("sufficient_data"):
        print(f"\nDrift score: {ds['score']:.4f}")
    else:
        print("\nDrift score: insufficient data")

    if digest["new_contradictions"]:
        print(f"\nContradictions ({len(digest['new_contradictions'])}):")
        for c in digest["new_contradictions"]:
            print(f"  [{c['type']}] {c['description']}")

    gap_count = sum(len(v) for v in digest["gaps"].values() if isinstance(v, list))
    print(f"\nGaps: {gap_count} total issues")
    return 0


def run_viz(args):
    """Render graph visualization as HTML or SVG."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    from cortex.viz.layout import fruchterman_reingold
    from cortex.viz.renderer import render_html, render_svg

    graph = _load_graph(input_path)

    def progress(current, total):
        print(f"\rLayout: {current}/{total}", end="", flush=True)

    layout = fruchterman_reingold(
        graph,
        iterations=args.iterations,
        max_nodes=args.max_nodes,
        progress=progress,
    )
    print()  # newline after progress

    output = Path(args.output)
    if args.viz_format == "svg":
        content = render_svg(graph, layout, width=args.width, height=args.height)
    else:
        content = render_html(graph, layout, width=args.width, height=args.height)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    print(f"Visualization saved to: {output}")

    if args.viz_format == "html" and not args.no_open:
        import webbrowser

        webbrowser.open(str(output.resolve()))
    return 0


def run_watch(args):
    """Monitor a directory for new export files."""
    import time as _time

    from cortex.sync.monitor import ExportMonitor

    watch_dir = Path(args.watch_dir)
    graph_path = Path(args.graph)

    if not watch_dir.is_dir():
        print(f"Not a directory: {watch_dir}")
        return 1

    def on_extract(path, graph):
        print(f"  Extracted from: {path.name} ({len(graph.nodes)} nodes)")

    monitor = ExportMonitor(
        watch_dir=watch_dir,
        graph_path=graph_path,
        interval=args.interval,
        on_extract=on_extract,
    )

    print(f"Watching {watch_dir} (interval: {args.interval}s)")
    print(f"Updating: {graph_path}")
    print("Press Ctrl+C to stop.")

    monitor.start()
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        print("\nMonitor stopped.")
    return 0


def run_sync_schedule(args):
    """Run periodic platform sync from config."""
    from cortex.sync.scheduler import SyncConfig, SyncScheduler

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    config = SyncConfig.from_file(config_path)
    scheduler = SyncScheduler(config)

    if args.once:
        print(f"Running {len(config.schedules)} sync(s)...")
        results = scheduler.run_once()
        for platform, paths in results.items():
            if paths:
                print(f"  {platform}: {', '.join(str(p) for p in paths)}")
            else:
                print(f"  {platform}: no output (check config)")
        return 0

    import time as _time

    print(f"Starting scheduled sync ({len(config.schedules)} schedules)...")
    print("Press Ctrl+C to stop.")
    scheduler.start()
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        print("\nScheduler stopped.")
    return 0


def run_extract_coding(args):
    """Extract identity signals from coding tool sessions."""
    # Watch mode — continuous extraction
    if getattr(args, "watch", False):
        from cortex.continuous import watch_coding_sessions

        output_path = Path(args.output) if args.output else Path("coding_context.json")
        watch_coding_sessions(
            graph_path=str(output_path),
            project_filter=args.project,
            interval=args.interval,
            settle_seconds=args.settle,
            enrich=getattr(args, "enrich", False),
            context_platforms=args.context_refresh,
            context_policy=args.context_policy,
            verbose=True,
        )
        return 0

    from cortex.coding import (
        aggregate_sessions,
        discover_claude_code_sessions,
        load_claude_code_session,
        parse_claude_code_session,
        session_to_context,
    )

    # Collect session files
    session_paths = []
    if args.discover:
        session_paths = discover_claude_code_sessions(
            project_filter=args.project,
            limit=args.limit,
        )
        if not session_paths:
            print("No Claude Code sessions found.")
            return 1
        if args.verbose:
            print(f"Discovered {len(session_paths)} session(s)")
    elif args.input_file:
        p = Path(args.input_file)
        if not p.exists():
            print(f"File not found: {p}")
            return 1
        session_paths = [p]
    else:
        print("Provide an input file or use --discover")
        return 1

    # Parse all sessions
    sessions = []
    for sp in session_paths:
        if args.verbose:
            print(f"  Parsing: {sp.name}")
        records = load_claude_code_session(sp)
        session = parse_claude_code_session(records)
        sessions.append(session)

    # Aggregate
    if len(sessions) > 1:
        combined = aggregate_sessions(sessions)
    else:
        combined = sessions[0]

    # Enrich with project files if requested
    if getattr(args, "enrich", False) and combined.project_path:
        from cortex.coding import enrich_session

        enrich_session(combined)

    # Stats
    if args.stats or args.verbose:
        print("\nCoding Session Summary:")
        print(f"  Sessions:     {len(sessions)}")
        print(f"  Files touched: {len(combined.files_touched)}")
        print(f"  Technologies: {', '.join(t for t, _ in combined.technologies.most_common(10))}")
        print(f"  Tools (bash): {', '.join(t for t, _ in combined.bash_tools.most_common(10))}")
        print(f"  User prompts: {len(combined.user_prompts)}")
        print(f"  Plan mode:    {'yes' if combined.plan_mode_used else 'no'}")
        print(f"  Test files:   {combined.test_files_written}")
        print(f"  Branches:     {', '.join(sorted(combined.branches)) or 'none'}")
        if combined.project_meta.enriched:
            pm = combined.project_meta
            print(f"  Project:      {pm.name}")
            if pm.description:
                print(f"  Description:  {pm.description[:100]}")
            if pm.license:
                print(f"  License:      {pm.license}")
            if pm.manifest_file:
                print(f"  Manifest:     {pm.manifest_file}")

    # Convert to v4 context
    ctx_data = session_to_context(combined)

    # Merge with existing context if requested
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            with open(merge_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            # Merge v4 categories from existing into ctx_data
            for category, topics in existing.get("categories", {}).items():
                if category not in ctx_data.setdefault("categories", {}):
                    ctx_data["categories"][category] = []
                existing_keys = {t.get("topic", "").lower() for t in ctx_data["categories"][category]}
                for topic in topics:
                    if topic.get("topic", "").lower() not in existing_keys:
                        ctx_data["categories"][category].append(topic)
            if args.verbose:
                print(f"\nMerged with {merge_path}")

    # Write output
    output_path = Path(args.output) if args.output else Path("coding_context.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ctx_data, f, indent=2, default=str)
    print(f"\nOutput: {output_path}")

    cat_counts = {k: len(v) for k, v in ctx_data.get("categories", {}).items() if v}
    if cat_counts:
        print(f"Extracted: {cat_counts}")

    return 0


def run_context_hook(args):
    """Install/manage Cortex context hook for Claude Code."""
    from cortex.hooks import (
        generate_compact_context_result,
        hook_status,
        install_hook,
        load_hook_config,
        uninstall_hook,
    )

    if args.action == "install":
        if not args.graph_file:
            print("Error: graph_file required for install")
            print("Usage: cortex context-hook install <graph.json>")
            return 1
        graph_path = Path(args.graph_file)
        if not graph_path.exists():
            print(f"File not found: {graph_path}")
            return 1
        cfg_path, settings_path = install_hook(
            graph_path=str(graph_path),
            policy=args.policy,
            max_chars=args.max_chars,
        )
        print("Cortex hook installed:")
        print(f"  Config:   {cfg_path}")
        print(f"  Settings: {settings_path}")
        print(f"  Policy:   {args.policy}")
        print("\nRestart Claude Code for the hook to take effect.")
        return 0

    elif args.action == "uninstall":
        removed = uninstall_hook()
        if removed:
            print("Cortex hook uninstalled.")
            print("Restart Claude Code to apply changes.")
        else:
            print("No Cortex hook found to remove.")
        return 0

    elif args.action == "test":
        config = load_hook_config()
        if not config.graph_path:
            print("No hook config found. Install first:")
            print("  python migrate.py context-hook install <graph.json>")
            return 1
        result = generate_compact_context_result(config)
        context = result.context
        if context:
            print("Context that would be injected:\n")
            print(context)
            print(f"\n({len(context)} chars)")
        else:
            print(f"No context generated ({result.reason.replace('_', ' ')}).")
            for warning in result.warnings:
                print(f"Warning: {warning}")
        return 0

    elif args.action == "status":
        status = hook_status()
        print(f"Installed: {'Yes' if status['installed'] else 'No'}")
        print(f"Config:    {status['config_path']}")
        print(f"Settings:  {status['settings_path']}")
        if status["config"]["graph_path"]:
            print(f"Graph:     {status['config']['graph_path']}")
            print(f"Policy:    {status['config']['policy']}")
            print(f"Max chars: {status['config']['max_chars']}")
        return 0

    return 1


def run_context_export(args):
    """Export compact context markdown to stdout."""
    from cortex.hooks import HookConfig, _load_graph, generate_compact_context_result

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        return 1

    if _load_graph(str(input_path)) is None:
        print(f"Error: invalid Cortex graph: {input_path}", file=sys.stderr)
        return 1

    config = HookConfig(
        graph_path=str(input_path),
        policy=args.policy,
        max_chars=args.max_chars,
    )
    result = generate_compact_context_result(config)
    if result.context:
        print(result.context)
    else:
        print(f"No context generated ({result.reason.replace('_', ' ')}).", file=sys.stderr)
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
    return 0


def run_context_write(args):
    """Write identity context to AI coding tool config files."""
    from cortex.context import CONTEXT_TARGETS, resolve_context_targets, watch_and_refresh, write_context

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    try:
        platforms = resolve_context_targets(args.platforms)
    except ValueError as exc:
        print(str(exc))
        print(f"Available: {', '.join(CONTEXT_TARGETS.keys())}, all")
        return 1

    if args.watch:
        watch_and_refresh(
            graph_path=str(input_path),
            platforms=platforms,
            project_dir=args.project,
            policy=args.policy,
            max_chars=args.max_chars,
            interval=args.interval,
        )
        return 0

    results = write_context(
        graph_path=str(input_path),
        platforms=platforms,
        project_dir=args.project,
        policy=args.policy,
        max_chars=args.max_chars,
        dry_run=args.dry_run,
    )

    for name, fpath, status in results:
        if status == "skipped":
            print(f"  {name}: skipped (no context or unknown platform)")
        elif status == "error":
            print(f"  {name}: error writing {fpath}")
        elif status == "dry-run":
            print(f"  {name}: {fpath} (dry-run)")
        else:
            print(f"  {name}: {status} {fpath}")

    return 0


def run_portable(args):
    """One-command portability flow: load or extract context, then install it across tools."""
    from cortex.hooks import _load_graph as load_graph_optional
    from cortex.minds import (
        adopt_graph_into_mind,
        load_mind_core_graph,
        resolve_default_mind,
        sync_mind_compatibility_targets,
    )
    from cortex.portability import resolve_portable_targets
    from cortex.portable_runtime import (
        merge_graphs,
        save_canonical_graph,
        sync_targets,
    )

    _emit_compatibility_note(
        "portable",
        "cortex mind ingest <mind> --from-detected ...",
        note="Use `cortex sync` when you only need to refresh already-ingested runtime context.",
        format_name=getattr(args, "format", None),
    )

    detected_selection = list(getattr(args, "from_detected", []) or [])
    project_dir = Path(args.project) if args.project else Path.cwd()
    detected_payload: dict[str, Any] | None = None

    if detected_selection and args.input_file:
        return _error("Use either an input file or `--from-detected`, not both.")
    if not detected_selection and not args.input_file:
        return _error("Provide an export file or use `--from-detected`.")

    try:
        targets = resolve_portable_targets(args.to)
    except ValueError as exc:
        return _error(str(exc))

    input_path: Path | None = None
    graph: CortexGraph | None = None
    detected_kind = "detected" if detected_selection else "graph"
    extracted_stats = None
    try:
        redactor = _build_pii_redactor(
            args,
            default_enabled=bool(detected_selection and not getattr(args, "no_redact_detected", False)),
        )
    except FileNotFoundError as exc:
        return _missing_path_error(Path(exc.args[0]), label="Redaction patterns file")

    if redactor is not None and args.format != "json":
        if detected_selection and not args.redact:
            _echo("PII redaction enabled for detected local sources")
        else:
            _echo("PII redaction enabled")

    if detected_selection:
        try:
            detected_payload = _load_detected_sources_or_error(
                args,
                project_dir=project_dir,
                announce=args.format != "json" and not _CLI_QUIET,
                redactor=redactor,
            )
        except ValueError as exc:
            lines = str(exc).splitlines()
            return _error(lines[0], hint="\n".join(lines[1:]) or None)
        graph = detected_payload["graph"]
        input_path = project_dir / "detected_sources.json"
        extracted_stats = _graph_category_stats(graph)
        if args.format != "json":
            _echo(
                f"Detected sources: {len(detected_payload['selected_sources'])} selected, "
                f"{len(detected_payload['skipped_sources'])} skipped"
            )
    else:
        input_path = Path(args.input_file)
        if not input_path.exists():
            return _missing_path_error(input_path, label="Input file")
        graph = load_graph_optional(str(input_path))

    if graph is None and input_path is not None:
        try:
            data, detected_format = load_file(input_path)
        except PermissionError:
            return _permission_error(input_path, action="read the input file")
        except Exception as exc:  # pragma: no cover - same behavior as extract
            return _error(str(exc))

        fmt = args.input_format if args.input_format != "auto" else detected_format
        extractor = AggressiveExtractor(redactor=redactor)
        v4_data = _run_extraction(extractor, data, fmt)
        graph = upgrade_v4_to_v5(v4_data)
        detected_kind = fmt
        extracted_stats = extractor.context.stats()

    output_dir = Path(args.output)
    store_dir = Path(args.store_dir)
    try:
        default_mind = resolve_default_mind(store_dir)
    except (FileNotFoundError, ValueError) as exc:
        return _error(str(exc))

    identity = None
    identity_path = store_dir / "identity.json"
    if identity_path.exists():
        from cortex.upai.identity import UPAIIdentity

        identity = UPAIIdentity.load(store_dir)

    graph_path_for_installs = output_dir / "context.json"
    if default_mind:
        try:
            if args.dry_run:
                base_payload = load_mind_core_graph(store_dir, default_mind)
                payload = sync_mind_compatibility_targets(
                    store_dir,
                    default_mind,
                    targets=targets,
                    project_dir=project_dir,
                    smart=False,
                    policy_name=args.policy,
                    max_chars=args.max_chars,
                    output_dir=output_dir,
                    persist_state=False,
                    graph=merge_graphs(base_payload["graph"], graph),
                    graph_ref=str(base_payload["graph_ref"]),
                    graph_source="default_mind_preview",
                )
            else:
                adopted = adopt_graph_into_mind(
                    store_dir,
                    default_mind,
                    graph,
                    message=f"Portable adoption into default Mind `{default_mind}`",
                    source="compat.portable",
                )
                payload = sync_mind_compatibility_targets(
                    store_dir,
                    default_mind,
                    targets=targets,
                    project_dir=project_dir,
                    smart=False,
                    policy_name=args.policy,
                    max_chars=args.max_chars,
                    output_dir=output_dir,
                )
                payload["branch"] = adopted["branch"]
                payload["branch_name"] = adopted["branch_name"]
                payload["version_id"] = adopted["version_id"]
            graph_path_for_installs = Path(payload["graph_path"])
        except PermissionError:
            return _permission_error(output_dir, action="write portability files")
        except OSError as exc:
            return _error(f"Could not write portability files into {output_dir}: {exc}")
    else:
        if not args.dry_run:
            try:
                state, graph_path_for_installs = save_canonical_graph(
                    store_dir, graph, graph_path=output_dir / "context.json"
                )
                payload = sync_targets(
                    graph,
                    targets=targets,
                    store_dir=store_dir,
                    project_dir=str(project_dir),
                    output_dir=output_dir,
                    graph_path=graph_path_for_installs,
                    policy_name=args.policy,
                    smart=False,
                    max_chars=args.max_chars,
                    dry_run=False,
                    state=state,
                    identity=identity,
                )
            except PermissionError:
                return _permission_error(output_dir, action="write portability files")
            except OSError as exc:
                return _error(f"Could not write portability files into {output_dir}: {exc}")
        else:
            payload = {
                "source": detected_kind,
                "input_path": str(input_path),
                "graph_path": str(output_dir / "context.json"),
                "targets": sync_targets(
                    graph,
                    targets=targets,
                    store_dir=store_dir,
                    project_dir=str(project_dir),
                    output_dir=output_dir,
                    graph_path=output_dir / "context.json",
                    policy_name=args.policy,
                    smart=False,
                    max_chars=args.max_chars,
                    dry_run=True,
                    identity=identity,
                )["targets"],
            }

    payload = {
        **payload,
        "source": detected_kind,
        "graph_path": str(graph_path_for_installs),
        "context_path": str(graph_path_for_installs),
        "target_count": len(payload.get("targets", [])),
    }
    if default_mind:
        payload["mind"] = default_mind
        payload["compatibility_mode"] = "default_mind"
    if extracted_stats is not None:
        payload["extracted"] = extracted_stats
    if detected_payload is not None:
        payload["selected_sources"] = detected_payload["selected_sources"]
        payload["skipped_sources"] = detected_payload["skipped_sources"]
        payload["detected_source_count"] = len(detected_payload["detected_sources"])
    if _emit_result(payload, args.format) == 0:
        return 0

    _echo("Portable context ready:")
    if default_mind:
        _echo(f"  default Mind: {default_mind}")
    _echo(f"  context: {graph_path_for_installs}" + (" (dry-run)" if args.dry_run else ""))
    _echo(f"  source: {detected_kind}")
    if extracted_stats is not None and (args.verbose or True):
        _echo(f"  extracted: {extracted_stats['total']} topics across {len(extracted_stats['by_category'])} categories")

    if payload["targets"]:
        _echo("\nTargets:")
        for result in payload["targets"]:
            joined = ", ".join(result["paths"]) if result["paths"] else "(no files)"
            _echo(f"  {result['target']}: {joined} [{result['status']}]")
            if result.get("note"):
                _echo(f"    {result['note']}")

    return 0


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
