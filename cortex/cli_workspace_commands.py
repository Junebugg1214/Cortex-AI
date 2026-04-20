#!/usr/bin/env python3
"""Workspace-facing command handlers for the Cortex CLI."""

from __future__ import annotations

import getpass
import json
import os
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cortex.atomic_io import atomic_write_text
from cortex.cli_surface import HELP_TOPIC_TEXT

DOCTOR_STORE_ENTRY_NAMES = (
    "HEAD",
    "history.json",
    "refs",
    "versions",
    "minds",
    "packs",
    "portable",
    "claims.jsonl",
    "governance.json",
    "remotes.json",
    "identity.json",
    "identity.key",
    "keychain.json",
    "merge_state.json",
    "merge_working.json",
    "federation_state.json",
    "maintenance_audit.json",
    "logs",
    "cortex.db",
)
DOCTOR_STORE_SIGNATURE_NAMES = {
    "HEAD",
    "history.json",
    "refs",
    "versions",
    "minds",
    "packs",
    "cortex.db",
    "claims.jsonl",
    "governance.json",
    "remotes.json",
    "identity.key",
    "keychain.json",
    "merge_state.json",
    "merge_working.json",
    "federation_state.json",
    "maintenance_audit.json",
}


@dataclass(frozen=True)
class WorkspaceCliContext:
    """Callbacks supplied by the main CLI module."""

    emit_result: Callable[[Any, str], int]
    echo: Callable[..., None]
    error: Callable[..., int]
    emit_compatibility_note: Callable[..., None]
    resolve_first_class_store_selection: Callable[..., Any]
    resolve_store_selection: Callable[..., Any]
    resolved_store_dir: Callable[[str | Path | None], Path]


def _default_owner_name() -> str:
    return getpass.getuser().strip() or "owner"


def _default_mind_label(owner: str) -> str:
    try:
        import pwd

        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",", 1)[0].strip()
    except Exception:  # pragma: no cover - platform-dependent
        gecos = ""
    return gecos or owner.replace("-", " ").replace("_", " ").title() or "Self"


def _write_default_config(config_path: Path, *, namespace: str) -> tuple[str, str]:
    reader_token = f"cortex-reader-{secrets.token_hex(24)}"
    writer_token = f"cortex-writer-{secrets.token_hex(24)}"
    payload = (
        "[runtime]\n"
        'store_dir = "."\n'
        'mode = "local-single-user"\n'
        "\n"
        "[server]\n"
        'host = "127.0.0.1"\n'
        "port = 8766\n"
        "\n"
        "[mcp]\n"
        f'namespace = "{namespace}"\n'
        "\n"
        "[[auth.keys]]\n"
        'name = "reader"\n'
        f'token = "{reader_token}"\n'
        'scopes = ["read"]\n'
        f'namespaces = ["{namespace}"]\n'
        "\n"
        "[[auth.keys]]\n"
        'name = "writer"\n'
        f'token = "{writer_token}"\n'
        'scopes = ["write", "branch", "merge", "index"]\n'
        f'namespaces = ["{namespace}"]\n'
    )
    atomic_write_text(config_path, payload, encoding="utf-8", file_mode=0o600)
    return reader_token, writer_token


def run_init(args, *, ctx: WorkspaceCliContext) -> int:
    from cortex.config import load_selfhost_config
    from cortex.graph.minds import default_mind_status, init_mind, list_minds, set_default_mind

    try:
        selection = ctx.resolve_first_class_store_selection(args.store_dir, command="init")
    except ValueError as exc:
        return ctx.error(str(exc))
    store_dir = selection.store_dir
    store_dir.mkdir(parents=True, exist_ok=True)
    config_path = store_dir / "config.toml"

    config_created = False
    reader_token = ""
    if not config_path.exists():
        reader_token, _writer_token = _write_default_config(config_path, namespace=args.namespace)
        config_created = True

    try:
        config = load_selfhost_config(config_path=config_path, env={})
    except ValueError as exc:
        return ctx.error(str(exc))

    created_mind = False
    created_mind_id = ""
    default_mind = ""
    owner = args.owner.strip() or _default_owner_name()
    label = args.label.strip() or _default_mind_label(owner)

    if not args.no_mind:
        try:
            current_default = default_mind_status(store_dir)
        except (FileNotFoundError, ValueError):
            current_default = {"configured": False, "mind": ""}

        if current_default.get("configured"):
            default_mind = str(current_default["mind"])
        else:
            known_minds = [item["mind"] for item in list_minds(store_dir)["minds"]]
            target_mind = (args.mind or "self").strip() or "self"
            if len(known_minds) == 1:
                target_mind = known_minds[0]
            if target_mind not in known_minds:
                try:
                    init_mind(
                        store_dir,
                        target_mind,
                        kind=args.kind,
                        label=label,
                        owner=owner,
                        default_policy=args.default_policy,
                    )
                except (FileExistsError, ValueError) as exc:
                    return ctx.error(str(exc))
                created_mind = True
                created_mind_id = target_mind
            try:
                payload = set_default_mind(store_dir, target_mind)
            except (FileNotFoundError, ValueError) as exc:
                return ctx.error(str(exc))
            default_mind = str(payload["mind"])

    next_steps = []
    if default_mind:
        next_steps.append(f'cortex mind remember {default_mind} "I prefer concise technical answers."')
        next_steps.append(f"cortex mind status {default_mind}")
    next_steps.append("cortex doctor")

    payload = {
        "status": "ok",
        "store_dir": str(store_dir.resolve()),
        "store_source": selection.source,
        "config_path": str(config_path.resolve()),
        "config_created": config_created,
        "auth_keys_created": 2 if config_created else 0,
        "default_mind": default_mind,
        "created_mind": created_mind,
        "created_mind_id": created_mind_id,
        "namespace": config.mcp_namespace or args.namespace,
        "warnings": list(selection.warnings),
        "next_steps": next_steps,
    }
    if ctx.emit_result(payload, args.format) == 0:
        return 0

    ctx.echo(f"Initialized Cortex at {payload['store_dir']}")
    ctx.echo(f"  config: {payload['config_path']}" + (" (created)" if config_created else " (reused)"))
    ctx.echo(f"  store source: {payload['store_source']}")
    if default_mind:
        ctx.echo(f"  default Mind: {default_mind}" + (" (created)" if created_mind else " (reused)"))
    else:
        ctx.echo("  default Mind: not configured")
    if config_created:
        ctx.echo("  auth keys: generated reader + writer tokens")
    for warning in payload["warnings"]:
        ctx.echo(f"  warning: {warning}")
    ctx.echo("")
    ctx.echo("Next:")
    for step in next_steps:
        ctx.echo(f"  {step}")
    if reader_token:
        ctx.echo("")
        ctx.echo("Important: keep the generated API keys from config.toml private.")
    return 0


def run_help_topic(args, *, ctx: WorkspaceCliContext) -> int:
    ctx.echo(HELP_TOPIC_TEXT.get(args.topic, HELP_TOPIC_TEXT["overview"]), force=True)
    return 0


def run_scan(args, *, ctx: WorkspaceCliContext) -> int:
    from cortex.portability.portable_runtime import bar, scan_portability

    store_dir = ctx.resolved_store_dir(args.store_dir)
    payload = scan_portability(
        store_dir=store_dir,
        project_dir=Path(args.project) if args.project else Path.cwd(),
        extra_roots=[Path(root) for root in args.search_root],
    )
    if ctx.emit_result(payload, args.format) == 0:
        return 0

    ctx.echo(f"Found {len(payload['tools'])} AI tools:\n")
    for tool in payload["tools"]:
        line = f"  {tool['name']:<12} {bar(tool['coverage'])}  {tool['fact_count']:>3} facts"
        if tool["note"]:
            line += f"  ({tool['note']})"
        ctx.echo(line)
    percent = round(payload["coverage"] * 100)
    ctx.echo(f"\nYour AI tools know {percent}% of your full context.")
    adoptable_targets = payload.get("adoptable_targets", [])
    metadata_only_targets = [
        target for target in payload.get("metadata_only_targets", []) if target not in set(adoptable_targets)
    ]
    if adoptable_targets:
        joined = " ".join(adoptable_targets)
        ctx.echo(
            f"Run `cortex portable --from-detected {joined} --to all --project .` to adopt detected local context."
        )
    elif metadata_only_targets:
        joined = " ".join(metadata_only_targets)
        ctx.echo(
            f"Run `cortex portable --from-detected {joined} --to all --project . --include-config-metadata` to record detected MCP setup metadata."
        )
    else:
        ctx.echo("Run `cortex sync --smart` or `cortex remember` to fix this.")
    return 0


def run_remember(args, *, ctx: WorkspaceCliContext) -> int:
    from cortex.graph.minds import load_mind_core_graph, remember_and_sync_default_mind, resolve_default_mind
    from cortex.portability.portable_graphs import extract_graph_from_statement, merge_graphs
    from cortex.portability.portable_runtime import (
        ALL_PORTABLE_TARGETS,
        canonical_target_name,
        default_output_dir,
        load_portability_state,
        remember_and_sync,
        sync_targets,
    )

    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def _outside_project_paths(payload: dict[str, Any]) -> list[Path]:
        outside: list[Path] = []
        seen: set[Path] = set()
        for target in payload.get("targets", []):
            for raw_path in target.get("paths", []):
                if not raw_path:
                    continue
                path = Path(str(raw_path)).expanduser().resolve()
                if _is_within(path, project_dir):
                    continue
                if path not in seen:
                    outside.append(path)
                    seen.add(path)
        return outside

    def _preview_payload(default_mind: str | None) -> dict[str, Any]:
        targets = list(args.to or ALL_PORTABLE_TARGETS)
        if default_mind:
            state = load_portability_state(store_dir)
            base_payload = load_mind_core_graph(store_dir, default_mind)
            merged = merge_graphs(base_payload["graph"], extract_graph_from_statement(args.statement))
            output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
            return {
                "targets": sync_targets(
                    merged,
                    targets=[canonical_target_name(target) for target in targets],
                    store_dir=store_dir,
                    project_dir=str(project_dir),
                    output_dir=output_dir,
                    graph_path=output_dir / "context.json",
                    policy_name=args.policy,
                    smart=args.smart,
                    max_chars=args.max_chars,
                    dry_run=True,
                    state=state,
                    persist_state=False,
                )["targets"]
            }
        return remember_and_sync(
            args.statement,
            store_dir=store_dir,
            project_dir=project_dir,
            targets=targets,
            smart=args.smart,
            policy_name=args.policy,
            max_chars=args.max_chars,
            dry_run=True,
        )

    def _global_scope_error(paths: list[Path]) -> int:
        rendered_paths = "\n".join(f"  - {path}" for path in paths)
        return ctx.error(
            "The following paths are outside --project and will be written:\n"
            f"{rendered_paths}\n"
            "Re-run with --global to confirm, or use --to PROJECT_TARGET to narrow."
        )

    ctx.emit_compatibility_note(
        "remember",
        'cortex mind remember <mind> "..."',
        note="The default-Mind compatibility layer keeps this command working, but new workflows should target a named Mind directly.",
        format_name=getattr(args, "format", None),
    )

    store_dir = ctx.resolved_store_dir(args.store_dir)
    project_dir = Path(args.project) if args.project else Path.cwd()
    try:
        default_mind = resolve_default_mind(store_dir)
    except (FileNotFoundError, ValueError) as exc:
        return ctx.error(str(exc))

    preview_payload = _preview_payload(default_mind)
    outside_paths = _outside_project_paths(preview_payload)
    if outside_paths and not args.dry_run and not getattr(args, "allow_global", False):
        return _global_scope_error(outside_paths)

    if default_mind and not args.dry_run:
        payload = remember_and_sync_default_mind(
            store_dir,
            default_mind,
            statement=args.statement,
            project_dir=project_dir,
            targets=list(args.to or ALL_PORTABLE_TARGETS),
            smart=args.smart,
            policy_name=args.policy,
            max_chars=args.max_chars,
        )
    else:
        payload = remember_and_sync(
            args.statement,
            store_dir=store_dir,
            project_dir=project_dir,
            targets=args.to,
            smart=args.smart,
            policy_name=args.policy,
            max_chars=args.max_chars,
            dry_run=args.dry_run,
        )
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    if default_mind and not args.dry_run:
        ctx.echo(f"Remembered once via default Mind `{default_mind}`. Updated:")
    else:
        ctx.echo("Remembered once. Updated:")
    for target in payload["targets"]:
        joined = ", ".join(target["paths"]) if target["paths"] else "(no files)"
        ctx.echo(f"  {target['target']:<12} → {joined}")
    return 0


def run_status(args, *, ctx: WorkspaceCliContext) -> int:
    from cortex.portability.portable_runtime import status_portability

    store_dir = ctx.resolved_store_dir(args.store_dir)
    payload = status_portability(
        store_dir=store_dir,
        project_dir=Path(args.project) if args.project else Path.cwd(),
    )
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    if not payload["issues"]:
        ctx.echo("No stale or missing context detected.")
        return 0
    for issue in payload["issues"]:
        prefix = "WARN" if issue["stale"] else "OK"
        line = f"{prefix} {issue['name']}"
        if issue["stale_days"] is not None:
            line += f" - {issue['stale_days']} days since last update"
        ctx.echo(line)
        if issue["missing_labels"]:
            ctx.echo("  Missing: " + "; ".join(issue["missing_labels"]))
        if issue.get("unexpected_labels"):
            ctx.echo("  Drifted: " + "; ".join(issue["unexpected_labels"]))
        if issue.get("missing_paths"):
            ctx.echo("  Missing files: " + "; ".join(issue["missing_paths"]))
    return 0


def run_build(args, *, ctx: WorkspaceCliContext) -> int:
    from cortex.portability.portable_runtime import build_digital_footprint

    ctx.emit_compatibility_note(
        "build",
        "cortex mind ingest <mind> --from-detected ...",
        note="Use `cortex pack` when you want reusable domain knowledge instead of a compatibility-era portability import.",
        format_name=getattr(args, "format", None),
    )

    store_dir = ctx.resolved_store_dir(args.store_dir)
    try:
        payload = build_digital_footprint(
            sources=args.sources,
            inputs=args.inputs,
            store_dir=store_dir,
            project_dir=Path(args.project) if args.project else Path.cwd(),
            search_roots=[Path(root) for root in args.search_root],
            sync_after=args.sync,
            targets=args.to,
            smart=args.smart,
            policy_name=args.policy,
            max_chars=args.max_chars,
        )
    except ValueError as exc:
        return ctx.error(str(exc))
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    for source in payload["sources"]:
        ctx.echo(f"{source['source']}: {json.dumps(source, ensure_ascii=False)}")
    ctx.echo(f"Built context graph with {payload['fact_count']} facts")
    return 0


def run_audit(args, *, ctx: WorkspaceCliContext) -> int:
    from cortex.portability.portable_runtime import audit_portability

    ctx.emit_compatibility_note(
        "audit",
        "cortex doctor",
        note="Use `cortex status` for runtime drift checks once your workspace is healthy.",
        format_name=getattr(args, "format", None),
    )

    store_dir = ctx.resolved_store_dir(args.store_dir)
    payload = audit_portability(
        store_dir=store_dir,
        project_dir=Path(args.project) if args.project else Path.cwd(),
    )
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    if not payload["issues"]:
        ctx.echo("No cross-platform conflicts detected.")
        return 0
    ctx.echo("Detected context conflicts:\n")
    for issue in payload["issues"]:
        tag = issue.get("tag", "portable")
        ctx.echo(f"  [{tag}] {issue['message']}")
    return 0


def _doctor_workspace_paths(store_dir: Path) -> tuple[Path, Path]:
    resolved = store_dir.resolve()
    if resolved.name == ".cortex":
        return resolved.parent, resolved
    return resolved, (resolved / ".cortex").resolve()


def _doctor_store_entries(root: Path) -> list[str]:
    return [name for name in DOCTOR_STORE_ENTRY_NAMES if (root / name).exists()]


def _doctor_has_store_signature(entries: list[str]) -> bool:
    return any(name in DOCTOR_STORE_SIGNATURE_NAMES for name in entries)


def _doctor_raw_config_payload(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    from cortex.config import _load_toml

    if not path.exists():
        return None, None
    try:
        payload = _load_toml(path)
    except Exception as exc:  # pragma: no cover - parse details vary slightly by interpreter
        return None, str(exc)
    return payload, None


def _doctor_is_cortex_config(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    return bool({"runtime", "server", "mcp", "auth"} & set(payload))


def _doctor_runtime_store_dir(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    runtime = payload.get("runtime") or {}
    if not isinstance(runtime, dict):
        return None
    value = runtime.get("store_dir")
    if value is None:
        return None
    return str(value).strip()


def _doctor_render_normalized_config_store_dir(config_path: Path, *, desired: str = ".") -> str | None:
    original = config_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    updated: list[str] = []
    runtime_found = False
    in_runtime = False
    store_written = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_runtime and not store_written:
                updated.append(f'store_dir = "{desired}"')
                store_written = True
            in_runtime = stripped == "[runtime]"
            runtime_found = runtime_found or in_runtime
            updated.append(line)
            continue
        if in_runtime and "=" in stripped and stripped.split("=", 1)[0].strip() == "store_dir":
            indent = line[: len(line) - len(line.lstrip())]
            updated.append(f'{indent}store_dir = "{desired}"')
            store_written = True
            continue
        updated.append(line)

    if in_runtime and not store_written:
        updated.append(f'store_dir = "{desired}"')
        store_written = True

    if not runtime_found:
        updated = ["[runtime]", f'store_dir = "{desired}"', "", *updated]
        store_written = True

    normalized = "\n".join(updated).strip() + "\n"
    if normalized == original.strip() + "\n":
        return None
    return normalized


def _doctor_repair_backup_dir(canonical_store: Path) -> Path:
    return canonical_store / "doctor-backups" / secrets.token_hex(6)


def _doctor_backup_copy(source: Path, *, backup_dir: Path, workspace_root: Path) -> str:
    try:
        relative = source.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        relative = Path(source.name)
    destination = backup_dir / relative
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return str(destination)


def _doctor_collect_store_diagnosis(store_dir: Path) -> dict[str, Any]:
    from cortex.config import load_selfhost_config

    resolved_store = store_dir.resolve()
    workspace_root, canonical_store = _doctor_workspace_paths(resolved_store)
    root_entries = _doctor_store_entries(workspace_root)
    has_root_store = _doctor_has_store_signature(root_entries)
    root_config_path = workspace_root / "config.toml"
    canonical_config_path = canonical_store / "config.toml"
    root_config_payload, root_config_error = (
        _doctor_raw_config_payload(root_config_path) if root_config_path != canonical_config_path else (None, None)
    )
    canonical_config_payload, canonical_config_error = _doctor_raw_config_payload(canonical_config_path)
    root_config_is_cortex = _doctor_is_cortex_config(root_config_payload)
    issues: list[dict[str, Any]] = []

    if resolved_store != canonical_store and has_root_store:
        issues.append(
            {
                "code": "root_store_layout",
                "severity": "warning",
                "message": (
                    f"The active store resolves to {resolved_store}, not the canonical {canonical_store}. "
                    "This usually means Cortex runtime files are spilling into the workspace root."
                ),
                "fixable": True,
                "entries": list(root_entries),
            }
        )

    if resolved_store == canonical_store and has_root_store:
        issues.append(
            {
                "code": "accidental_second_store",
                "severity": "warning",
                "message": (
                    f"Detected Cortex store artifacts next to the active .cortex store in {workspace_root}. "
                    "This looks like an accidental second store."
                ),
                "fixable": True,
                "entries": list(root_entries),
            }
        )

    if root_config_error and root_config_path != canonical_config_path:
        issues.append(
            {
                "code": "root_config_parse_error",
                "severity": "warning",
                "message": f"Could not parse {root_config_path}: {root_config_error}",
                "fixable": False,
                "path": str(root_config_path),
            }
        )
    elif root_config_is_cortex:
        raw_store_dir = _doctor_runtime_store_dir(root_config_payload)
        issues.append(
            {
                "code": "root_config_outside_store",
                "severity": "warning",
                "message": (
                    f"Found a Cortex config outside .cortex at {root_config_path}. "
                    + (
                        'Because it uses `store_dir = "."`, it can make Cortex write into the workspace root.'
                        if raw_store_dir == "."
                        else "First-class Cortex CLI flows discover `.cortex/config.toml`, not a root-level config.toml."
                    )
                ),
                "fixable": not canonical_config_path.exists(),
                "path": str(root_config_path),
                "raw_store_dir": raw_store_dir,
            }
        )

    if canonical_config_error:
        issues.append(
            {
                "code": "canonical_config_parse_error",
                "severity": "warning",
                "message": f"Could not parse {canonical_config_path}: {canonical_config_error}",
                "fixable": False,
                "path": str(canonical_config_path),
            }
        )
    elif canonical_config_path.exists():
        try:
            canonical_config = load_selfhost_config(config_path=canonical_config_path, env={})
        except ValueError as exc:
            issues.append(
                {
                    "code": "canonical_config_invalid",
                    "severity": "warning",
                    "message": f"Could not load {canonical_config_path}: {exc}",
                    "fixable": False,
                    "path": str(canonical_config_path),
                }
            )
        else:
            raw_store_dir = _doctor_runtime_store_dir(canonical_config_payload)
            raw_store_matches_canonical = False
            if raw_store_dir:
                raw_store_path = Path(raw_store_dir)
                if raw_store_path.is_absolute():
                    raw_store_matches_canonical = raw_store_path.resolve() == canonical_store
            if canonical_config.store_dir.resolve() != canonical_store:
                issues.append(
                    {
                        "code": "config_store_mismatch",
                        "severity": "warning",
                        "message": (
                            f"{canonical_config_path} resolves store_dir to {canonical_config.store_dir.resolve()}, "
                            f"but the canonical store is {canonical_store}."
                        ),
                        "fixable": True,
                        "path": str(canonical_config_path),
                    }
                )
            elif raw_store_dir not in (".",) and not raw_store_matches_canonical:
                issues.append(
                    {
                        "code": "config_store_dir_not_dot",
                        "severity": "warning",
                        "message": (
                            f'{canonical_config_path} should pin `[runtime].store_dir = "."` '
                            "so the active store remains stable and discoverable."
                        ),
                        "fixable": True,
                        "path": str(canonical_config_path),
                        "raw_store_dir": raw_store_dir,
                    }
                )

    return {
        "active_store_dir": resolved_store,
        "workspace_root": workspace_root,
        "canonical_store_dir": canonical_store,
        "root_store_entries": root_entries,
        "repairable_root_entries": root_entries if has_root_store else [],
        "root_config_path": root_config_path if root_config_is_cortex else None,
        "canonical_config_path": canonical_config_path,
        "issues": issues,
    }


def _doctor_apply_store_repairs(
    diagnosis: dict[str, Any],
    *,
    dry_run: bool = False,
    backup_repair: bool = False,
) -> dict[str, Any]:
    workspace_root = Path(diagnosis["workspace_root"])
    canonical_store = Path(diagnosis["canonical_store_dir"])
    root_entries = list(diagnosis["repairable_root_entries"])
    root_config_path = diagnosis["root_config_path"]
    canonical_config_path = Path(diagnosis["canonical_config_path"])
    actions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    errors: list[str] = []
    backup_copies: list[dict[str, Any]] = []
    backup_dir = ""

    planned_backups: list[Path] = []
    if root_config_path is not None:
        source_config = Path(root_config_path)
        if source_config.exists() and source_config != canonical_config_path:
            planned_backups.append(source_config)
    for name in root_entries:
        source_path = workspace_root / name
        if source_path.exists():
            planned_backups.append(source_path)
    if (
        canonical_config_path.exists()
        and _doctor_render_normalized_config_store_dir(canonical_config_path, desired=".") is not None
    ):
        planned_backups.append(canonical_config_path)

    if backup_repair and planned_backups and not dry_run:
        backup_root = _doctor_repair_backup_dir(canonical_store)
        for source in planned_backups:
            try:
                copied_path = _doctor_backup_copy(source, backup_dir=backup_root, workspace_root=workspace_root)
            except Exception as exc:
                errors.append(f"Could not back up {source}: {exc}")
            else:
                backup_dir = str(backup_root)
                backup_copies.append({"source": str(source), "backup": copied_path})

    if not dry_run:
        canonical_store.mkdir(parents=True, exist_ok=True)

    if root_config_path is not None:
        source_config = Path(root_config_path)
        if source_config.exists() and source_config != canonical_config_path:
            action = {
                "action": "move_config",
                "source": str(source_config),
                "destination": str(canonical_config_path),
                "dry_run": bool(dry_run),
            }
            if canonical_config_path.exists():
                conflicts.append(
                    {
                        **action,
                        "reason": "destination_exists",
                        "message": (
                            f"Cannot move {source_config} into {canonical_config_path} because the canonical config already exists."
                        ),
                    }
                )
            elif dry_run:
                actions.append(action)
            else:
                canonical_config_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source_config), str(canonical_config_path))
                actions.append(action)

    for name in root_entries:
        source_path = workspace_root / name
        destination_path = canonical_store / name
        if not source_path.exists():
            skipped.append(
                {
                    "action": "move_store_entry",
                    "entry": name,
                    "source": str(source_path),
                    "destination": str(destination_path),
                    "reason": "source_missing",
                }
            )
            continue
        action = {
            "action": "move_store_entry",
            "entry": name,
            "source": str(source_path),
            "destination": str(destination_path),
            "dry_run": bool(dry_run),
        }
        if destination_path.exists():
            conflicts.append(
                {
                    **action,
                    "reason": "destination_exists",
                    "message": f"Cannot move {source_path} into {destination_path} because the destination already exists.",
                }
            )
            continue
        if dry_run:
            actions.append(action)
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        actions.append(action)

    if canonical_config_path.exists():
        normalized_text = _doctor_render_normalized_config_store_dir(canonical_config_path, desired=".")
        if normalized_text is not None:
            action = {
                "action": "normalize_config_store_dir",
                "path": str(canonical_config_path),
                "store_dir": ".",
                "dry_run": bool(dry_run),
            }
            if dry_run:
                actions.append(action)
            else:
                atomic_write_text(canonical_config_path, normalized_text, encoding="utf-8")
                actions.append(action)

    return {
        "applied": bool(actions) and not dry_run,
        "dry_run": bool(dry_run),
        "store_dir": str(canonical_store),
        "actions": actions,
        "skipped": skipped,
        "conflicts": conflicts,
        "errors": errors,
        "backup_dir": backup_dir,
        "backup_copies": backup_copies,
    }


def run_doctor(args, *, ctx: WorkspaceCliContext) -> int:
    from cortex.config import CortexSelfHostConfig, load_selfhost_config, startup_diagnostics
    from cortex.portability.context import _resolve_path
    from cortex.portability.portable_runtime import (
        SMART_ROUTE_TAGS,
        load_canonical_graph,
        load_portability_state,
        scan_portability,
    )
    from cortex.release import PROJECT_VERSION

    selection = ctx.resolve_store_selection(args.store_dir)
    store_dir = selection.store_dir.resolve()
    project_dir = Path(args.project) if args.project else Path.cwd()
    fix_requested = args.fix or args.fix_store
    diagnosis = _doctor_collect_store_diagnosis(store_dir)
    repair_report: dict[str, Any] | None = None
    effective_store_dir = store_dir

    if fix_requested:
        repair_report = _doctor_apply_store_repairs(
            diagnosis,
            dry_run=args.dry_run,
            backup_repair=args.backup_repair,
        )
        effective_store_dir = Path(repair_report["store_dir"]).resolve()
        if not args.dry_run:
            diagnosis = _doctor_collect_store_diagnosis(effective_store_dir)

    state = load_portability_state(effective_store_dir)
    graph, graph_path = load_canonical_graph(effective_store_dir, state)
    include_portability = bool(args.portability or args.format == "json")
    scan = scan_portability(store_dir=effective_store_dir, project_dir=project_dir) if include_portability else None
    config_path = effective_store_dir / "config.toml"
    runtime_config_error = ""
    try:
        config = load_selfhost_config(
            store_dir=effective_store_dir, config_path=config_path if config_path.exists() else None, env={}
        )
    except ValueError as exc:
        runtime_config_error = str(exc)
        config = CortexSelfHostConfig(
            store_dir=effective_store_dir, config_path=config_path if config_path.exists() else None
        )
    runtime_diagnostics = startup_diagnostics(config, mode="server")
    if runtime_config_error:
        runtime_diagnostics["warnings"] = [
            *runtime_diagnostics["warnings"],
            f"Config load fallback: {runtime_config_error}",
        ]

    try:
        import nacl  # noqa: F401

        crypto_available = True
    except Exception:  # pragma: no cover
        crypto_available = False

    issues = diagnosis["issues"]
    fix_available = any(issue.get("fixable") for issue in issues)
    repair_actions = repair_report["actions"] if repair_report else []
    repair_skipped = repair_report["skipped"] if repair_report else []
    repair_conflicts = repair_report["conflicts"] if repair_report else []
    repair_errors = repair_report["errors"] if repair_report else []
    repair_backup_dir = repair_report["backup_dir"] if repair_report else ""
    repair_backup_copies = repair_report["backup_copies"] if repair_report else []
    advice: list[str]
    if args.dry_run and fix_requested:
        advice = [
            "Review the planned repair actions, then rerun `cortex doctor --fix` or `--fix-store` without `--dry-run`.",
        ]
    elif repair_conflicts and repair_actions:
        advice = [
            "Resolve the reported repair conflicts, then rerun `cortex doctor --fix`.",
            "Run `cortex doctor` again after cleanup to confirm the store is stable.",
        ]
    elif repair_conflicts or repair_errors:
        advice = [
            "Resolve the reported repair conflicts or errors, then rerun `cortex doctor --fix`.",
        ]
    elif repair_actions:
        advice = [
            "Run `cortex doctor` again to confirm the store is stable.",
            "Run `cortex init` if you still need config or auth bootstrap help.",
        ]
    elif fix_requested and not repair_actions and not repair_errors:
        advice = ["No safe store repairs were needed."]
    elif fix_available:
        advice = ["Run `cortex doctor --fix-store` to normalize the active store back into `.cortex/`."]
    elif not graph.nodes:
        advice = [
            "Run `cortex init` if this workspace still needs a default Mind and config bootstrap.",
            'Then run `cortex mind remember self "..."` or `cortex mind ingest self --from-detected ...` to create canonical memory.',
        ]
    else:
        advice = [
            "Run `cortex connect <runtime> --check` to verify runtime wiring before you mount or serve Cortex state.",
            "Run `cortex doctor --portability` when you need tool coverage and smart-routing detail.",
        ]

    status = "ok"
    if args.dry_run and fix_requested:
        status = "dry-run"
    elif repair_conflicts or repair_errors:
        status = "partial" if repair_actions else "failed"
    elif repair_actions:
        status = "fixed"
    elif issues:
        status = "warn"

    payload = {
        "status": status,
        "release": PROJECT_VERSION,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "workspace": {
            "project_dir": str(project_dir.resolve()),
            "active_store_dir": str(effective_store_dir.resolve()),
            "canonical_store_dir": str(Path(diagnosis["canonical_store_dir"]).resolve()),
            "workspace_root": str(Path(diagnosis["workspace_root"]).resolve()),
            "store_source": selection.source if effective_store_dir == store_dir else "doctor_fix",
            "warnings": list(selection.warnings),
        },
        "store": {
            "active_store_dir": str(effective_store_dir.resolve()),
            "canonical_store_dir": str(Path(diagnosis["canonical_store_dir"]).resolve()),
            "root_store_entries": list(diagnosis["root_store_entries"]),
            "repairable_root_entries": list(diagnosis["repairable_root_entries"]),
            "issue_codes": [
                issue["code"] for issue in issues if issue["code"] in {"root_store_layout", "accidental_second_store"}
            ],
        },
        "config": {
            "path": str(config.config_path) if config and config.config_path else None,
            "exists": bool(config_path.exists()),
            "runtime_store_dir": _doctor_runtime_store_dir(_doctor_raw_config_payload(config_path)[0])
            if config_path.exists()
            else None,
            "issue_codes": [
                issue["code"]
                for issue in issues
                if issue["code"]
                in {
                    "root_config_parse_error",
                    "root_config_outside_store",
                    "canonical_config_parse_error",
                    "canonical_config_invalid",
                    "config_store_mismatch",
                    "config_store_dir_not_dot",
                }
            ],
        },
        "runtime": runtime_diagnostics,
        "graph": {
            "path": str(graph_path),
            "exists": graph_path.exists(),
            "fact_count": len(graph.nodes),
        },
        "portability": {
            "included": include_portability,
            "coverage": scan["coverage"] if scan else None,
            "configured_tools": [tool["target"] for tool in scan["tools"] if tool["configured"]] if scan else [],
            "smart_routing": SMART_ROUTE_TAGS if scan else {},
        },
        "repairs": {
            "fix_requested": fix_requested,
            "fix_available": fix_available,
            "actions": repair_actions,
            "skipped": repair_skipped,
            "conflicts": repair_conflicts,
            "errors": repair_errors,
            "backup_dir": repair_backup_dir,
            "backup_copies": repair_backup_copies,
        },
        "store_dir": str(effective_store_dir.resolve()),
        "project_dir": str(project_dir.resolve()),
        "store_source": selection.source if effective_store_dir == store_dir else "doctor_fix",
        "config_path": str(config.config_path) if config and config.config_path else None,
        "canonical_graph_path": str(graph_path),
        "canonical_graph_exists": graph_path.exists(),
        "fact_count": len(graph.nodes),
        "coverage": scan["coverage"] if scan else None,
        "configured_tools": [tool["target"] for tool in scan["tools"] if tool["configured"]] if scan else [],
        "smart_routing": SMART_ROUTE_TAGS if scan else {},
        "sample_paths": {
            "claude-code": str(_resolve_path("{home}/.claude/CLAUDE.md", str(project_dir))),
            "codex": str(_resolve_path("{project}/AGENTS.md", str(project_dir))),
            "cursor": str(_resolve_path("{project}/.cursor/rules/cortex.mdc", str(project_dir))),
            "hermes": str(_resolve_path("{home}/.hermes/memories/USER.md", str(project_dir))),
        },
        "crypto_available": crypto_available,
        "warnings": list(selection.warnings),
        "issues": issues,
        "fix_requested": fix_requested,
        "fix_available": fix_available,
        "repair_actions": repair_actions,
        "repair_skipped": repair_skipped,
        "repair_conflicts": repair_conflicts,
        "repair_errors": repair_errors,
        "repair_backup_dir": repair_backup_dir,
        "repair_backup_copies": repair_backup_copies,
        "advice": advice,
    }
    if ctx.emit_result(payload, args.format) == 0:
        return 0

    ctx.echo("Cortex doctor")
    ctx.echo(f"  Status:   {payload['status']}")
    ctx.echo(f"  Release:  {payload['release']}")
    ctx.echo(f"  Python:   {payload['python']}")
    ctx.echo("")
    ctx.echo("Workspace")
    ctx.echo(f"  Project:         {payload['workspace']['project_dir']}")
    ctx.echo(f"  Active store:    {payload['workspace']['active_store_dir']}")
    ctx.echo(f"  Canonical store: {payload['workspace']['canonical_store_dir']}")
    ctx.echo(f"  Store source:    {payload['workspace']['store_source']}")
    for warning in payload["warnings"]:
        ctx.echo(f"  Warning:         {warning}")
    ctx.echo("")
    ctx.echo("Config")
    ctx.echo(f"  Path:            {payload['config']['path'] or '(none)'}")
    ctx.echo(f"  Exists:          {'yes' if payload['config']['exists'] else 'no'}")
    if payload["config"]["runtime_store_dir"]:
        ctx.echo(f"  runtime.store_dir: {payload['config']['runtime_store_dir']}")
    ctx.echo("")
    ctx.echo("Runtime")
    ctx.echo(f"  Mode:            {payload['runtime']['runtime_mode']}")
    ctx.echo(f"  Auth enabled:    {'yes' if payload['runtime']['auth_enabled'] else 'no'}")
    ctx.echo(f"  API keys:        {payload['runtime']['api_key_count']}")
    ctx.echo(f"  Bind scope:      {payload['runtime']['bind_scope']}")
    if payload["runtime"]["mcp_namespace"]:
        ctx.echo(f"  MCP namespace:   {payload['runtime']['mcp_namespace']}")
    if payload["runtime"].get("request_policy"):
        request_policy = payload["runtime"]["request_policy"]
        rate_limit = request_policy["rate_limit_per_minute"]
        rate_limit_text = f"{rate_limit}/min" if rate_limit else "disabled"
        ctx.echo(
            "  Requests:        "
            + f"max {request_policy['max_body_bytes']} bytes, "
            + f"timeout {request_policy['read_timeout_seconds']}s, "
            + f"rate limit {rate_limit_text}"
        )
    ctx.echo(f"  Crypto:          {'installed' if crypto_available else 'not installed'}")
    for warning in payload["runtime"]["warnings"]:
        ctx.echo(f"  Runtime warning: {warning}")
    ctx.echo("")
    ctx.echo("Graph")
    ctx.echo(f"  Path:            {payload['graph']['path']}")
    ctx.echo(f"  Present:         {'yes' if payload['graph']['exists'] else 'no'}")
    ctx.echo(f"  Facts:           {payload['graph']['fact_count']}")
    ctx.echo("")
    if args.portability:
        ctx.echo("Portability")
        ctx.echo(f"  Coverage:        {round((payload['portability']['coverage'] or 0.0) * 100)}%")
        ctx.echo(f"  Configured tools: {', '.join(payload['portability']['configured_tools']) or '(none)'}")
        if payload["portability"]["smart_routing"]:
            ctx.echo("  Smart routing:")
            for target, tags in payload["portability"]["smart_routing"].items():
                ctx.echo(f"    {target:<12} -> {', '.join(tags)}")
        ctx.echo("")
    ctx.echo("Issues")
    if not payload["issues"]:
        ctx.echo("  none")
    for issue in payload["issues"]:
        ctx.echo(f"  [{issue['code']}] {issue['message']}")
    for action in payload["repair_actions"]:
        description = action.get("action", "repair")
        if action.get("entry"):
            description += f" ({action['entry']})"
        if action.get("dry_run"):
            description += " [dry-run]"
        ctx.echo(f"  Repair action:   {description}")
    for skipped in payload["repair_skipped"]:
        description = skipped.get("action", "repair")
        if skipped.get("entry"):
            description += f" ({skipped['entry']})"
        ctx.echo(f"  Repair skipped:  {description} [{skipped.get('reason', 'skipped')}]")
    for conflict in payload["repair_conflicts"]:
        description = conflict.get("action", "repair")
        if conflict.get("entry"):
            description += f" ({conflict['entry']})"
        ctx.echo(f"  Repair conflict: {description} [{conflict.get('reason', 'conflict')}]")
    for error in payload["repair_errors"]:
        ctx.echo(f"  Repair warning:  {error}")
    if payload["repair_backup_dir"]:
        ctx.echo(f"  Repair backup:   {payload['repair_backup_dir']}")
    ctx.echo("")
    for hint in payload["advice"]:
        ctx.echo(f"Next: {hint}")
    return 0


__all__ = [
    "WorkspaceCliContext",
    "run_audit",
    "run_build",
    "run_doctor",
    "run_help_topic",
    "run_init",
    "run_remember",
    "run_scan",
    "run_status",
]
