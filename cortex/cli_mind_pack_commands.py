#!/usr/bin/env python3
"""Mind and Brainpack command handlers for the Cortex CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class MindPackCliContext:
    """Callbacks supplied by the main CLI module."""

    emit_result: Callable[[Any, str], int]
    echo: Callable[..., None]
    error: Callable[..., int]
    missing_path_error: Callable[..., int]
    build_pii_redactor: Callable[..., Any]
    resolved_store_dir: Callable[[str | Path | None], Path]


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_cli_bool(value: str) -> bool:
    cleaned = str(value).strip().lower()
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Boolean value must be one of true/false, yes/no, or 1/0, got: {value}")


def run_pack(args, *, ctx: MindPackCliContext):
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

    store_dir = ctx.resolved_store_dir(getattr(args, "store_dir", None))

    if args.pack_subcommand == "init":
        try:
            payload = init_pack(
                store_dir,
                args.name,
                description=args.description,
                owner=args.owner,
            )
        except (FileExistsError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Created Brainpack `{payload['pack']}` at {payload['path']}")
        return 0

    if args.pack_subcommand == "list":
        payload = list_packs(store_dir)
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not payload["packs"]:
            ctx.echo("No Brainpacks found yet.")
            return 0
        ctx.echo(f"Found {payload['count']} Brainpack(s):\n")
        for item in payload["packs"]:
            compiled = item["compiled_at"] or "not compiled yet"
            ctx.echo(
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Ingested {payload['ingested_count']} source(s) into `{payload['pack']}`.")
        ctx.echo(f"Total indexed sources: {payload['source_count']}")
        return 0

    if args.pack_subcommand == "compile":
        try:
            payload = compile_pack(
                store_dir,
                args.name,
                incremental=args.incremental,
                suggest_questions=args.suggest_questions,
                max_summary_chars=args.max_summary_chars,
                mode=args.mode,
                output_path=args.output,
            )
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Compiled `{payload['pack']}`:")
        ctx.echo(f"  mode: {payload['compile_mode']}")
        ctx.echo(f"  sources: {payload['source_count']} total, {payload['text_source_count']} readable")
        ctx.echo(f"  graph: {payload['graph_nodes']} nodes / {payload['graph_edges']} edges")
        ctx.echo(f"  wiki: {payload['article_count']} page(s)")
        ctx.echo(f"  claims: {payload['claim_count']}")
        ctx.echo(f"  unknowns: {payload['unknown_count']}")
        ctx.echo(f"  graph path: {payload['graph_path']}")
        if payload.get("output_file"):
            ctx.echo(f"  artifact: {payload['output_file']}")
        return 0

    if args.pack_subcommand == "inspect":
        from cortex.packs import inspect_pack_artifact

        try:
            payload = inspect_pack_artifact(args.path, show_provenance=args.show_provenance)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Pack artifact: {payload['path']}")
        ctx.echo(f"  mode: {payload['compile_mode']}")
        ctx.echo(f"  provenance available: {payload['provenance_available']}")
        ctx.echo(f"  lossy: {payload['lossy']}")
        ctx.echo(f"  graph: {payload['graph_nodes']} nodes / {payload['graph_edges']} edges")
        if payload.get("provenance_nodes"):
            ctx.echo("  provenance nodes:")
            for item in payload["provenance_nodes"][:10]:
                ctx.echo(
                    f"    {item['label']}: provenance={item['provenance_count']} "
                    f"history={item['claim_history_count']} contested={item['contested']}"
                )
        return 0

    if args.pack_subcommand == "status":
        try:
            payload = pack_status(store_dir, args.name)
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Brainpack `{payload['pack']}`")
        if payload["manifest"]["description"]:
            ctx.echo(f"  {payload['manifest']['description']}")
        ctx.echo(
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
        ctx.echo(f"  compiled: {payload['compiled_at'] or 'not compiled yet'}")
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Brainpack `{payload['pack']}` → {payload['name']}")
        ctx.echo(f"  {payload['fact_count']} routed facts via {payload['mode']} mode")
        if payload["context_markdown"]:
            ctx.echo("")
            ctx.echo(payload["context_markdown"], force=True)
        elif payload["message"]:
            ctx.echo(payload["message"])
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Mounted Brainpack `{payload['pack']}`:")
        for item in payload["targets"]:
            note = f"  {item['note']}" if item.get("note") else ""
            ctx.echo(f"  {item['target']:<12} {item['status']}{note}")
            for path in item.get("paths", []):
                ctx.echo(f"    → {path}")
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Brainpack `{payload['pack']}` query: {payload['query']}")
        ctx.echo(
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
            ctx.echo("  No strong matches yet. Try compiling more sources or broadening the query.")
            return 0
        ctx.echo("")
        for item in payload["results"]:
            extra = item.get("path") or item.get("source_path") or ""
            suffix = f" ({extra})" if extra else ""
            ctx.echo(f"- [{item['kind']}] {item['title']}: {item.get('summary', '')}{suffix}".rstrip())
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Brainpack `{payload['pack']}` answered: {payload['question']}")
        ctx.echo(f"  {payload['summary']}")
        if payload["artifact_written"]:
            ctx.echo(f"  saved: {payload['artifact_path']}")
        elif payload["message"]:
            ctx.echo(f"  {payload['message']}")
        ctx.echo("")
        ctx.echo(payload["answer_markdown"], force=True)
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Brainpack `{payload['pack']}` lint: {payload['lint_status']}")
        ctx.echo(
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
            ctx.echo("")
            for item in payload["findings"][:8]:
                ctx.echo(f"- [{item['level']}] {item['title']}: {item['detail']}")
        else:
            ctx.echo("  No Brainpack integrity issues detected.")
        if payload["suggestions"]:
            ctx.echo("")
            ctx.echo("Suggestions:")
            for suggestion in payload["suggestions"]:
                ctx.echo(f"- {suggestion}")
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Exported Brainpack `{payload['pack']}`")
        ctx.echo(f"  archive: {payload['archive']}")
        ctx.echo(
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
            ctx.echo("  Missing reference sources:")
            for item in payload["missing_reference_sources"][:8]:
                ctx.echo(f"  - {item}")
        return 0

    if args.pack_subcommand == "import":
        try:
            payload = import_pack_bundle(
                args.archive,
                store_dir,
                as_name=args.as_name,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Imported Brainpack `{payload['pack']}` from {payload['archive']}")
        if payload["pack"] != payload["original_pack"]:
            ctx.echo(f"  original pack: {payload['original_pack']}")
        ctx.echo(
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

    return ctx.error(
        "Specify a pack subcommand: init, list, ingest, compile, inspect, status, context, mount, query, ask, lint, export, import"
    )


def run_mind(args, *, ctx: MindPackCliContext):
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

    store_dir = ctx.resolved_store_dir(args.store_dir)

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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Created Mind `{payload['mind']}` at {payload['path']}")
        return 0

    if args.mind_subcommand == "list":
        payload = list_minds(store_dir)
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not payload["minds"]:
            ctx.echo("No Cortex Minds found yet.")
            return 0
        ctx.echo(f"Found {payload['count']} Mind(s):\n")
        for item in payload["minds"]:
            suffix = "  default" if item.get("is_default") else ""
            ctx.echo(
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if payload["configured"]:
            ctx.echo(f"Default Mind: `{payload['mind']}` ({payload['source']})")
        else:
            ctx.echo("No default Mind configured.")
        return 0

    if args.mind_subcommand == "ingest":
        project_dir = Path(args.project) if getattr(args, "project", None) else Path.cwd()
        try:
            redactor = ctx.build_pii_redactor(
                args,
                default_enabled=not getattr(args, "no_redact_detected", False),
            )
        except FileNotFoundError as exc:
            return ctx.missing_path_error(Path(exc.args[0]), label="Redaction patterns file")
        if redactor is not None and args.format != "json":
            if not args.redact:
                ctx.echo("PII redaction enabled for detected local sources")
            else:
                ctx.echo("PII redaction enabled")
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
            return ctx.error(lines[0], hint="\n".join(lines[1:]) or None)
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(
            f"Mind `{payload['mind']}` queued {payload['proposed_source_count']} detected source(s)"
            f" for review as `{payload['proposal_id']}`"
        )
        ctx.echo(
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Mind `{payload['mind']}`")
        ctx.echo(f"  {payload['manifest']['label']} · {payload['manifest']['kind']}")
        ctx.echo(
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
        ctx.echo(f"  graph ref: {payload['graph_ref']}")
        if payload["attached_brainpacks"]:
            ctx.echo("  attached packs:")
            for item in payload["attached_brainpacks"]:
                extra = []
                if item["activation"]["always_on"]:
                    extra.append("always-on")
                if item["activation"]["targets"]:
                    extra.append("targets=" + ",".join(item["activation"]["targets"]))
                if item["mounted_targets"]:
                    extra.append("mounted=" + ",".join(item["mounted_targets"]))
                suffix = f" ({'; '.join(extra)})" if extra else ""
                ctx.echo(f"    - {item['pack']} · {item['compile_status']} · priority {item['priority']}{suffix}")
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Mind `{payload['mind']}` remembered:")
        ctx.echo(f"  {payload['statement']}")
        ctx.echo(
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
            ctx.echo("  refreshed mounts:")
            for item in payload["targets"]:
                note = f"  {item['note']}" if item.get("note") else ""
                ctx.echo(f"    {item['target']:<12} {item.get('status', 'ok')}{note}")
        else:
            ctx.echo("  no persisted mounts to refresh.")
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        verb = "Updated" if payload["updated"] else "Attached"
        ctx.echo(f"{verb} Brainpack `{payload['pack']}` on Mind `{payload['mind']}`")
        ctx.echo(f"  total attachments: {payload['attachment_count']}")
        return 0

    if args.mind_subcommand == "detach-pack":
        try:
            payload = detach_pack_from_mind(
                store_dir,
                args.name,
                args.pack,
            )
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Detached Brainpack `{payload['pack']}` from Mind `{payload['mind']}`")
        ctx.echo(f"  total attachments: {payload['attachment_count']}")
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Mind `{payload['mind']}` → {payload['name']}")
        ctx.echo(
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
            ctx.echo("  included packs: " + ", ".join(item["pack"] for item in payload["included_brainpacks"]))
        if payload["context_markdown"]:
            ctx.echo("")
            ctx.echo(payload["context_markdown"], force=True)
        elif payload["message"]:
            ctx.echo(payload["message"])
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
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Mounted Mind `{payload['mind']}`:")
        for item in payload["targets"]:
            note = f"  {item['note']}" if item.get("note") else ""
            ctx.echo(f"  {item['target']:<12} {item['status']}{note}")
            for path in item.get("paths", []):
                ctx.echo(f"    → {path}")
        ctx.echo(f"  total persisted mounts: {payload['mount_count']}")
        return 0

    if args.mind_subcommand == "mounts":
        try:
            payload = list_mind_mounts(store_dir, args.name)
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Mind `{payload['mind']}` mount records")
        if not payload["mounts"]:
            ctx.echo("  No persisted mounts yet.")
            return 0
        for item in payload["mounts"]:
            extra = []
            if item.get("task"):
                extra.append(f"task={item['task']}")
            if item.get("activation_target") and item["activation_target"] != item["target"]:
                extra.append(f"activation={item['activation_target']}")
            suffix = f" ({'; '.join(extra)})" if extra else ""
            ctx.echo(f"  {item['target']:<12} {item.get('status', 'ok')}{suffix}")
            for path in item.get("paths", []):
                ctx.echo(f"    → {path}")
        return 0

    return ctx.error(
        "Specify a mind subcommand: init, list, status, default, ingest, remember, attach-pack, detach-pack, compose, mount, mounts"
    )


def run_sources(args, *, ctx: MindPackCliContext):
    from cortex.claims import RetractionPlanningError, retract_graph_source
    from cortex.minds import _persist_mind_core_graph, load_mind_core_graph
    from cortex.sources import SourceRegistry, graph_source_ids

    store_dir = ctx.resolved_store_dir(args.store_dir)

    if args.sources_subcommand == "list":
        try:
            mind_payload = load_mind_core_graph(store_dir, args.mind)
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        graph = mind_payload["graph"]
        registry = SourceRegistry.for_store(store_dir)
        records = registry.list_records(stable_ids=graph_source_ids(graph))
        payload = {
            "status": "ok",
            "mind": args.mind,
            "source_count": len(records),
            "sources": records,
        }
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not records:
            ctx.echo(f"Mind `{args.mind}` has no registered sources yet.")
            return 0
        ctx.echo(f"Mind `{args.mind}` sources")
        for item in records:
            labels = ", ".join(item.get("labels", []))
            ctx.echo(f"  {item['stable_id']} ({labels})")
        return 0

    if args.sources_subcommand == "retract":
        try:
            mind_payload = load_mind_core_graph(store_dir, args.mind)
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        graph = mind_payload["graph"]
        registry = SourceRegistry.for_store(store_dir)
        try:
            payload = retract_graph_source(
                graph,
                identifier=args.source_identifier,
                registry=registry,
                prune_orphans=not args.keep_orphans,
                dry_run=not args.confirm or args.dry_run,
                confirm=bool(args.confirm and not args.dry_run),
            )
        except RetractionPlanningError as exc:
            return ctx.error(str(exc))
        if args.confirm and not args.dry_run:
            persisted = _persist_mind_core_graph(
                store_dir,
                args.mind,
                graph,
                message=f"Retract source {payload['stable_source_id']} from Mind `{args.mind}`",
                source="sources.retract",
            )
            payload["version_id"] = persisted["version_id"]
            payload["graph_ref"] = persisted["graph_ref"]
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        verb = "Previewing" if payload.get("dry_run", False) else "Retracted"
        ctx.echo(f"{verb} source {payload['stable_source_id']} on Mind `{args.mind}`")
        ctx.echo(f"  labels: {', '.join(payload.get('labels', []))}")
        ctx.echo(f"  nodes pruned: {len(payload.get('pruned_nodes', []))}")
        ctx.echo(f"  edges pruned: {len(payload.get('pruned_edges', []))}")
        return 0

    return ctx.error("Specify a sources subcommand: list or retract")


def run_audience(args, *, ctx: MindPackCliContext):
    from cortex.audience.policy import AudiencePolicy, AudiencePolicyError, PolicyEngine, UnknownAudiencePolicyError
    from cortex.audience.templates import BUILTIN_AUDIENCE_TEMPLATES

    store_dir = ctx.resolved_store_dir(args.store_dir)
    engine = PolicyEngine(store_dir)

    if args.audience_subcommand == "add":
        try:
            policy = AudiencePolicy(
                audience_id=args.audience_id,
                display_name=args.display_name or args.audience_id.replace("-", " ").title(),
                allowed_node_types=_parse_csv_list(args.allowed_node_types),
                blocked_node_types=_parse_csv_list(args.blocked_node_types),
                allowed_claim_confidences=(args.confidence_min, args.confidence_max),
                redact_fields=_parse_csv_list(args.redact_fields),
                output_format=args.output_format,
                delivery=args.delivery,
                delivery_target=args.delivery_target,
                include_provenance=_parse_cli_bool(args.include_provenance),
                include_contested=_parse_cli_bool(args.include_contested),
            )
            payload = engine.add_policy(args.mind, policy)
        except (AudiencePolicyError, FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Saved audience `{payload['audience_id']}` on Mind `{payload['mind']}`")
        ctx.echo(f"  total policies: {payload['policy_count']}")
        return 0

    if args.audience_subcommand == "apply-template":
        template = BUILTIN_AUDIENCE_TEMPLATES[args.template]
        try:
            payload = engine.add_policy(args.mind, template)
        except (AudiencePolicyError, FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        payload["template"] = args.template
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Applied audience template `{args.template}` to Mind `{args.mind}`")
        return 0

    if args.audience_subcommand == "list":
        try:
            payload = engine.list_policies(args.mind)
        except (AudiencePolicyError, FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not payload["policies"]:
            ctx.echo(f"Mind `{args.mind}` has no configured audience policies.")
            return 0
        ctx.echo(f"Audience policies for Mind `{args.mind}`")
        for item in payload["policies"]:
            ctx.echo(f"  {item['audience_id']}: {item['output_format']} via {item['delivery']}")
        return 0

    if args.audience_subcommand == "preview":
        try:
            payload = engine.preview(args.mind, args.audience)
        except (AudiencePolicyError, FileNotFoundError, UnknownAudiencePolicyError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Audience preview `{args.audience}` for Mind `{args.mind}`")
        ctx.echo(f"  nodes: {payload['node_count_in']} -> {payload['node_count_out']}")
        ctx.echo(f"  redactions: {payload['redaction_count']}")
        return 0

    if args.audience_subcommand == "compile":
        try:
            payload = engine.compile(args.mind, args.audience)
        except (AudiencePolicyError, FileNotFoundError, UnknownAudiencePolicyError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Compiled audience `{args.audience}` for Mind `{args.mind}`")
        ctx.echo(f"  nodes: {payload['node_count_in']} -> {payload['node_count_out']}")
        if payload.get("delivered_to"):
            ctx.echo(f"  delivered to: {payload['delivered_to']}")
        elif isinstance(payload.get("output"), str):
            ctx.echo("")
            ctx.echo(payload["output"], force=True)
        return 0

    if args.audience_subcommand == "log":
        try:
            payload = engine.read_log(args.mind, args.audience or "")
        except (AudiencePolicyError, FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Audience log for Mind `{args.mind}`")
        for item in payload["entries"][:20]:
            ctx.echo(
                f"  {item['timestamp']} {item['audience_id']}: "
                f"{item['node_count_in']} -> {item['node_count_out']} "
                f"(redactions={item['redaction_count']})"
            )
        return 0

    return ctx.error("Specify an audience subcommand: add, list, preview, compile, log, or apply-template")


__all__ = [
    "MindPackCliContext",
    "run_audience",
    "run_mind",
    "run_pack",
    "run_sources",
]
