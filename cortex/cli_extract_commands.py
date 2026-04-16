#!/usr/bin/env python3
"""Extraction, ingest, import, and migrate command handlers for the Cortex CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cortex import cli_parser as cli_parser_module
from cortex.compat import upgrade_v4_to_v5
from cortex.extract_memory import (
    AggressiveExtractor,
    PIIRedactor,
    build_eval_compat_view,
    load_file,
    merge_contexts,
)
from cortex.extraction import collect_bulk_texts, get_bulk_backend, merged_v4_from_results
from cortex.graph import CortexGraph
from cortex.sources import SourceRegistry


@dataclass(frozen=True)
class ExtractCliContext:
    """Callbacks supplied by the main CLI module."""

    echo: Callable[..., None]
    error: Callable[..., int]
    is_quiet: Callable[[], bool]
    load_graph: Callable[[Path], CortexGraph]
    missing_path_error: Callable[..., int]
    permission_error: Callable[..., int]


def export_dispatch() -> dict[str, tuple[object, str, bool]]:
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


def confidence_thresholds() -> dict[str, float]:
    from cortex.import_memory import CONFIDENCE_THRESHOLDS

    return CONFIDENCE_THRESHOLDS


def normalized_context_cls():
    from cortex.import_memory import NormalizedContext

    return NormalizedContext


def run_extraction(extractor, data, fmt):
    """Route *data* through the correct extractor method and return the v4 dict."""
    backend = get_bulk_backend()
    if backend.__class__.__name__ == "HeuristicBackend":
        return merged_v4_from_results(
            backend.extract_bulk([], context={"extractor": extractor, "data": data, "fmt": fmt})
        )
    texts = collect_bulk_texts(data, fmt)
    return merged_v4_from_results(backend.extract_bulk(texts, context={"data": data, "fmt": fmt}))


def write_exports(ctx, min_conf, format_keys, output_dir, verbose=False):
    """Write the requested formats to *output_dir*. Returns list of (label, path)."""
    dispatch = export_dispatch()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for key in format_keys:
        export_fn, filename, is_json = dispatch[key]
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


def finalize_extraction_output(
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
    from cortex.temporal import apply_temporal_review_policy

    graph = upgrade_v4_to_v5(v4_output)
    apply_temporal_review_policy(graph)
    source = extraction_source_label(input_path)
    stable_source_id = source
    registry_payload: dict[str, Any] | None = None
    if input_path.exists():
        try:
            registry_payload = SourceRegistry.for_store(store_dir or input_path.parent).register_path(
                input_path,
                label=input_path.name,
                metadata={"input_format": fmt},
                force_reingest=True,
            )
            stable_source_id = str(registry_payload["stable_id"])
        except Exception:
            stable_source_id = source
    claim_count = 0
    metadata = {"input_format": fmt, "input_file": str(input_path)}
    metadata.update(dict(extra_metadata or {}))
    if registry_payload is not None:
        metadata["source_label"] = input_path.name
        metadata["source_id"] = stable_source_id

    if record_claims:
        stamp_graph_provenance(
            graph,
            source=source,
            method="extract",
            metadata=metadata,
            stable_source_id=stable_source_id,
            source_label=input_path.name,
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


def to_context_json_v5(data: dict) -> dict:
    """Normalize extraction output into the pinned portable context.json format."""
    return upgrade_v4_to_v5(data).export_v5()


def load_detected_sources_or_error(
    args,
    *,
    project_dir: Path,
    announce: bool = True,
    redactor: PIIRedactor | None = None,
    ctx: ExtractCliContext,
) -> dict[str, Any] | None:
    detected_selection = list(getattr(args, "from_detected", []) or [])
    if not detected_selection:
        return None

    from cortex.portable_runtime import extract_graph_from_detected_sources

    if announce:
        ctx.echo("Loading detected local sources")
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


def graph_category_stats(graph: CortexGraph) -> dict[str, Any]:
    categories = graph.export_v4().get("categories", {})
    return {
        "total": sum(len(items) for items in categories.values()),
        "by_category": {name: len(items) for name, items in categories.items()},
    }


def build_pii_redactor(args, *, default_enabled: bool = False) -> PIIRedactor | None:
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


def run_extract(args, *, ctx: ExtractCliContext) -> int:
    """Extract context from an export file and save as JSON."""
    detected_selection = list(getattr(args, "from_detected", []) or [])
    project_dir = Path(args.project) if getattr(args, "project", None) else Path.cwd()

    if detected_selection and args.input_file:
        return ctx.error("Use either an input file or `--from-detected`, not both.")
    if not detected_selection and not args.input_file:
        return ctx.error("Provide an export file or use `--from-detected`.")

    input_path: Path | None = None
    fmt = "detected" if detected_selection else "auto"
    detected_payload: dict[str, Any] | None = None
    try:
        redactor = build_pii_redactor(
            args,
            default_enabled=bool(detected_selection and not getattr(args, "no_redact_detected", False)),
        )
    except FileNotFoundError as exc:
        return ctx.missing_path_error(Path(exc.args[0]), label="Redaction patterns file")

    if redactor is not None and not bool(getattr(args, "json_output", False)):
        if detected_selection and not args.redact:
            ctx.echo("PII redaction enabled for detected local sources")
        else:
            ctx.echo("PII redaction enabled")

    if detected_selection:
        try:
            detected_payload = load_detected_sources_or_error(
                args,
                project_dir=project_dir,
                announce=not ctx.is_quiet() and not bool(getattr(args, "json_output", False)),
                redactor=redactor,
                ctx=ctx,
            )
        except ValueError as exc:
            lines = str(exc).splitlines()
            return ctx.error(lines[0], hint="\n".join(lines[1:]) or None)
        selected_sources = detected_payload["selected_sources"]
        result = detected_payload["graph"].export_v4()
        input_path = project_dir / "detected_sources.json"
        if not bool(getattr(args, "json_output", False)):
            ctx.echo(
                f"Detected sources: {len(selected_sources)} selected, "
                f"{len(detected_payload['skipped_sources'])} skipped"
            )
    else:
        input_path = Path(args.input_file)
        if not input_path.exists():
            return ctx.missing_path_error(input_path, label="Export file")

        ctx.echo(f"Loading: {input_path}")
        try:
            data, detected_format = load_file(input_path)
        except PermissionError:
            return ctx.permission_error(input_path, action="read the export file")
        except Exception as exc:
            return ctx.error(str(exc))

        fmt = args.format if args.format != "auto" else detected_format
        ctx.echo(f"Format: {fmt}")

    if not detected_selection:
        extractor = AggressiveExtractor(redactor=redactor)

        if args.merge:
            merge_path = Path(args.merge)
            if merge_path.exists():
                ctx.echo(f"Merging with existing context: {merge_path}")
                extractor = merge_contexts(merge_path, extractor)
            else:
                ctx.echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)

        result = run_extraction(extractor, data, fmt)
        stats = graph_category_stats(upgrade_v4_to_v5(result))
    else:
        if args.merge:
            merge_path = Path(args.merge)
            if merge_path.exists():
                existing = ctx.load_graph(merge_path)
                if existing is not None:
                    from cortex.portable_runtime import merge_graphs

                    result = merge_graphs(existing, upgrade_v4_to_v5(result)).export_v4()
            else:
                ctx.echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)
        stats = graph_category_stats(upgrade_v4_to_v5(result))
    claim_count = 0
    if not args.no_claims:
        result, claim_count = finalize_extraction_output(
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
    v5_output = to_context_json_v5(result)
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
        ctx.echo(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if (args.stats or args.verbose) and not json_only:
        for cat, count in sorted(stats["by_category"].items(), key=lambda item: -item[1]):
            ctx.echo(f"   {cat}: {count}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    try:
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(v5_output, handle, indent=2)
    except PermissionError:
        return ctx.permission_error(output_path, action="write context.json")
    except OSError as exc:
        return ctx.error(f"Could not write {output_path}: {exc}")
    if json_only:
        ctx.echo(json.dumps(payload, indent=2), force=True)
    else:
        ctx.echo(f"Saved to: {output_path}")
        if not args.no_claims:
            ctx.echo(f"Recorded {claim_count} claim event(s) to {Path(args.store_dir) / 'claims.jsonl'}")
    return 0


def run_ingest(args, *, ctx: ExtractCliContext) -> int:
    """Normalize connector input and extract it into Cortex memory."""
    from cortex.connectors import connector_to_text

    input_path = Path(args.input_file)
    if not input_path.exists():
        return ctx.missing_path_error(input_path, label="Connector input")

    ctx.echo(f"Loading connector input: {input_path}")
    try:
        normalized_text = connector_to_text(args.kind, input_path)
    except PermissionError:
        return ctx.permission_error(input_path, action="read connector input")
    except Exception as exc:
        return ctx.error(str(exc))

    if args.preview:
        ctx.echo(normalized_text.rstrip("\n"))
        return 0

    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                return ctx.missing_path_error(pp, label="Redaction patterns file")
            with pp.open("r", encoding="utf-8") as handle:
                custom_patterns = json.load(handle)
        redactor = PIIRedactor(custom_patterns)
        ctx.echo("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            ctx.echo(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            ctx.echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)

    result = extractor.process_plain_text(normalized_text)
    claim_count = 0
    if not args.no_claims:
        result, claim_count = finalize_extraction_output(
            result,
            input_path=input_path,
            fmt=f"connector:{args.kind}",
            store_dir=Path(args.store_dir),
            record_claims=True,
        )

    stats = extractor.context.stats()
    ctx.echo(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    try:
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(to_context_json_v5(result), handle, indent=2)
    except PermissionError:
        return ctx.permission_error(output_path, action="write context.json")
    except OSError as exc:
        return ctx.error(f"Could not write {output_path}: {exc}")
    ctx.echo(f"Saved to: {output_path}")
    if not args.no_claims:
        ctx.echo(f"Recorded {claim_count} claim event(s) to {Path(args.store_dir) / 'claims.jsonl'}")
    return 0


def run_import(args, *, ctx: ExtractCliContext) -> int:
    """Import a context JSON file and export to platform formats."""
    normalized_context = normalized_context_cls()
    thresholds = confidence_thresholds()

    input_path = Path(args.input_file)
    if not input_path.exists():
        return ctx.missing_path_error(input_path, label="Context file")

    ctx.echo(f"Loading: {input_path}")
    context = normalized_context.load(input_path)
    min_conf = thresholds[args.confidence]
    format_keys = cli_parser_module.PLATFORM_FORMATS[args.to]
    output_dir = Path(args.output)

    if args.dry_run:
        ctx.echo("\nDRY RUN PREVIEW")
        dispatch = export_dispatch()
        for key in format_keys:
            export_fn, filename, is_json = dispatch[key]
            result = export_fn(context, min_conf)
            ctx.echo(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                ctx.echo(line)
        return 0

    try:
        outputs = write_exports(context, min_conf, format_keys, output_dir, args.verbose)
    except PermissionError:
        return ctx.permission_error(output_dir, action="write exported files")
    except OSError as exc:
        return ctx.error(f"Could not write export files into {output_dir}: {exc}")

    ctx.echo(f"\nExported {len(outputs)} files to {output_dir}/:")
    for key, path in outputs:
        ctx.echo(f"   {key}: {path.name}")
    return 0


def run_migrate(args, *, ctx: ExtractCliContext) -> int:
    """Full pipeline: extract from export file, then import to platform formats."""
    normalized_context = normalized_context_cls()
    thresholds = confidence_thresholds()

    input_path = Path(args.input_file)
    if not input_path.exists():
        return ctx.missing_path_error(input_path, label="Input file")

    ctx.echo(f"Loading: {input_path}")
    try:
        data, detected_format = load_file(input_path)
    except PermissionError:
        return ctx.permission_error(input_path, action="read the input file")
    except Exception as exc:
        return ctx.error(str(exc))

    fmt = args.input_format if args.input_format != "auto" else detected_format
    ctx.echo(f"Format: {fmt}")

    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                return ctx.missing_path_error(pp, label="Redaction patterns file")
            with pp.open("r", encoding="utf-8") as handle:
                custom_patterns = json.load(handle)
        redactor = PIIRedactor(custom_patterns)
        ctx.echo("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            ctx.echo(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            ctx.echo(f"Merge file not found: {merge_path} (proceeding without merge)", stderr=True, force=True)

    v4_data = run_extraction(extractor, data, fmt)
    claim_count = 0
    if not args.no_claims and not args.dry_run:
        v4_data, claim_count = finalize_extraction_output(
            v4_data,
            input_path=input_path,
            fmt=fmt,
            store_dir=Path(args.store_dir),
            record_claims=True,
        )

    stats = extractor.context.stats()
    ctx.echo(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda item: -item[1]):
            ctx.echo(f"   {cat}: {count}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.schema == "v5":
        graph = upgrade_v4_to_v5(v4_data)

        if getattr(args, "discover_edges", False):
            from cortex.centrality import apply_centrality_boost, compute_centrality
            from cortex.cooccurrence import discover_edges as discover_cooccurrence
            from cortex.dedup import deduplicate
            from cortex.edge_extraction import discover_all_edges

            messages = getattr(extractor, "all_user_text", None)

            new_edges = discover_all_edges(graph, messages=messages)
            for edge in new_edges:
                graph.add_edge(edge)

            cooc_count = 0
            if messages and len(messages) >= 3:
                cooc_edges = discover_cooccurrence(messages, graph)
                for edge in cooc_edges:
                    graph.add_edge(edge)
                cooc_count = len(cooc_edges)

            merged = deduplicate(graph)

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
        with ctx_path.open("w", encoding="utf-8") as handle:
            json.dump(v5_data, handle, indent=2)
        if args.verbose:
            graph_stats = graph.stats()
            ctx.echo(f"   v5 graph: {graph_stats['node_count']} nodes, {graph_stats['edge_count']} edges")
            ctx.echo(f"   saved v5 context: {ctx_path}")
    else:
        ctx.echo("Warning: --schema v4 is deprecated. Prefer the default v5 context.json.", stderr=True, force=True)
        ctx_path = output_dir / "context.json"
        with ctx_path.open("w", encoding="utf-8") as handle:
            json.dump(v4_data, handle, indent=2)
        if args.verbose:
            ctx.echo(f"   saved intermediate context: {ctx_path}")

    context = normalized_context.from_v4(v4_data)
    min_conf = thresholds[args.confidence]
    format_keys = cli_parser_module.PLATFORM_FORMATS[args.to]

    if args.dry_run:
        ctx.echo("\nDRY RUN PREVIEW")
        dispatch = export_dispatch()
        for key in format_keys:
            export_fn, filename, is_json = dispatch[key]
            result = export_fn(context, min_conf)
            ctx.echo(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                ctx.echo(line)
        return 0

    try:
        outputs = write_exports(context, min_conf, format_keys, output_dir, args.verbose)
    except PermissionError:
        return ctx.permission_error(output_dir, action="write exported files")
    except OSError as exc:
        return ctx.error(f"Could not write export files into {output_dir}: {exc}")

    ctx.echo(f"\nExported {len(outputs) + 1} files to {output_dir}/:")
    ctx.echo("   context: context.json")
    for key, path in outputs:
        ctx.echo(f"   {key}: {path.name}")
    if not args.no_claims and not args.dry_run:
        ctx.echo(f"   claims: {claim_count} event(s) -> {Path(args.store_dir) / 'claims.jsonl'}")
    return 0
