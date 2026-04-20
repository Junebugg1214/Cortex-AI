#!/usr/bin/env python3
"""Portability-oriented command handlers for the Cortex CLI."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cortex.compat import upgrade_v4_to_v5
from cortex.extraction.extract_memory import AggressiveExtractor, load_file
from cortex.graph.graph import CortexGraph
from cortex.portability.adapters import ADAPTERS
from cortex.versioning.upai.disclosure import BUILTIN_POLICIES


@dataclass(frozen=True)
class PortableCliContext:
    """Callbacks supplied by the main CLI module."""

    cli_quiet: bool
    emit_result: Callable[[Any, str], int]
    echo: Callable[..., None]
    error: Callable[..., int]
    emit_compatibility_note: Callable[..., None]
    load_graph: Callable[[Path], CortexGraph]
    missing_path_error: Callable[..., int]
    no_context_error: Callable[[], int]
    permission_error: Callable[..., int]
    build_pii_redactor: Callable[..., Any]
    graph_category_stats: Callable[[CortexGraph], dict[str, Any]]
    load_detected_sources_or_error: Callable[..., dict[str, Any] | None]
    run_extraction: Callable[..., dict[str, Any]]


def run_sync(args, *, ctx: PortableCliContext) -> int:
    """Disclosure-filtered export via platform adapters or smart portability sync."""
    from cortex.cli_scope_guard import global_scope_error, outside_project_paths

    def _guard_portability_writes(payload: dict[str, Any], project_dir: Path) -> int | None:
        outside = outside_project_paths(payload, project_dir)
        if outside and not bool(getattr(args, "dry_run", False)) and not getattr(args, "allow_global", False):
            return global_scope_error(outside, error=ctx.error)
        return None

    def _sync_portability_targets(graph: CortexGraph, graph_path: Path, targets: list[str]) -> int:
        from cortex.portability.portability import resolve_portable_targets
        from cortex.portability.portable_runtime import (
            ALL_PORTABLE_TARGETS,
            load_portability_state,
            sync_targets,
        )

        store_dir = Path(args.store_dir)
        state = load_portability_state(store_dir)
        project_dir = (
            Path(args.project) if args.project else Path(state.project_dir) if state.project_dir else Path.cwd()
        )
        output_dir = Path(args.output)
        resolved_targets = resolve_portable_targets(targets)
        target_selection = ALL_PORTABLE_TARGETS if resolved_targets == list(ALL_PORTABLE_TARGETS) else resolved_targets
        try:
            preview_payload = sync_targets(
                graph,
                targets=target_selection,
                store_dir=store_dir,
                project_dir=str(project_dir),
                output_dir=output_dir,
                graph_path=graph_path,
                policy_name=args.policy,
                smart=bool(getattr(args, "smart", False)),
                max_chars=args.max_chars,
                dry_run=True,
                state=state,
                persist_state=False,
            )
        except PermissionError:
            return ctx.permission_error(output_dir, action="write synced portability files")
        except OSError as exc:
            return ctx.error(f"Could not sync portability files into {output_dir}: {exc}")
        if guard_result := _guard_portability_writes(preview_payload, project_dir):
            return guard_result
        try:
            payload = sync_targets(
                graph,
                targets=target_selection,
                store_dir=store_dir,
                project_dir=str(project_dir),
                output_dir=output_dir,
                graph_path=graph_path,
                policy_name=args.policy,
                smart=bool(getattr(args, "smart", False)),
                max_chars=args.max_chars,
                dry_run=bool(getattr(args, "dry_run", False)),
                state=state,
            )
        except PermissionError:
            return ctx.permission_error(output_dir, action="write synced portability files")
        except OSError as exc:
            return ctx.error(f"Could not sync portability files into {output_dir}: {exc}")
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        target_label = "all supported portability targets" if targets == ["all"] else ", ".join(resolved_targets)
        ctx.echo(f"Synced to {target_label}:")
        for target in payload["targets"]:
            label = target["target"]
            route = ", ".join(target.get("route_tags") or []) or "default route"
            ctx.echo(f"  {label:<12} → {route}")
        return 0

    if getattr(args, "smart", False):
        from cortex.graph.minds import load_mind_core_graph, resolve_default_mind, sync_mind_compatibility_targets
        from cortex.portability.portable_runtime import (
            ALL_PORTABLE_TARGETS,
            default_output_dir,
            load_canonical_graph,
            load_portability_state,
            sync_targets,
        )

        store_dir = Path(args.store_dir)
        if args.input_file:
            input_path = Path(args.input_file)
            if not input_path.exists():
                return ctx.missing_path_error(input_path, label="Context file")
            graph = ctx.load_graph(input_path)
            return _sync_portability_targets(graph, input_path, ["all"])

        try:
            default_mind = resolve_default_mind(store_dir)
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        if default_mind:
            project_dir = Path(args.project) if args.project else Path.cwd()
            state = load_portability_state(store_dir)
            output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
            try:
                base_payload = load_mind_core_graph(store_dir, default_mind)
                preview_payload = sync_targets(
                    base_payload["graph"],
                    targets=ALL_PORTABLE_TARGETS,
                    store_dir=store_dir,
                    project_dir=str(project_dir),
                    output_dir=output_dir,
                    graph_path=output_dir / "context.json",
                    policy_name=args.policy,
                    smart=True,
                    max_chars=args.max_chars,
                    dry_run=True,
                    state=state,
                    persist_state=False,
                )
            except (FileNotFoundError, ValueError) as exc:
                return ctx.error(str(exc))
            except PermissionError:
                return ctx.permission_error(output_dir, action="write synced portability files")
            except OSError as exc:
                return ctx.error(f"Could not sync portability files into {output_dir}: {exc}")
            if guard_result := _guard_portability_writes(preview_payload, project_dir):
                return guard_result
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
                return ctx.error(str(exc))
            if ctx.emit_result(payload, args.format) == 0:
                return 0
            ctx.echo(f"Smart context sync complete via default Mind `{default_mind}`:")
            for target in payload["targets"]:
                label = target["target"]
                ctx.echo(f"  {label:<12} → {', '.join(target['route_tags']) or 'default route'}")
            return 0

        state = load_portability_state(store_dir)
        graph, graph_path = load_canonical_graph(store_dir, state)
        if not graph.nodes:
            return ctx.no_context_error()
        project_dir = (
            Path(args.project) if args.project else Path(state.project_dir) if state.project_dir else Path.cwd()
        )
        output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
        try:
            preview_payload = sync_targets(
                graph,
                targets=ALL_PORTABLE_TARGETS,
                store_dir=store_dir,
                project_dir=str(project_dir),
                output_dir=output_dir,
                graph_path=graph_path,
                policy_name=args.policy,
                smart=True,
                max_chars=args.max_chars,
                dry_run=True,
                state=state,
                persist_state=False,
            )
        except PermissionError:
            return ctx.permission_error(output_dir, action="write synced portability files")
        except OSError as exc:
            return ctx.error(f"Could not sync portability files into {output_dir}: {exc}")
        if guard_result := _guard_portability_writes(preview_payload, project_dir):
            return guard_result
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
            return ctx.permission_error(output_dir, action="write synced portability files")
        except OSError as exc:
            return ctx.error(f"Could not sync portability files into {output_dir}: {exc}")
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo("Smart context sync complete:")
        for target in payload["targets"]:
            label = target["target"]
            ctx.echo(f"  {label:<12} → {', '.join(target['route_tags']) or 'default route'}")
        return 0

    input_path = Path(args.input_file)
    if not input_path.exists():
        return ctx.missing_path_error(input_path, label="Context file")

    if not args.to:
        return ctx.error("Specify --to for adapter export mode, or use --smart.")

    graph = ctx.load_graph(input_path)
    if args.to == "all" or args.to not in ADAPTERS:
        try:
            return _sync_portability_targets(graph, input_path, [args.to])
        except ValueError as exc:
            return ctx.error(str(exc))

    adapter = ADAPTERS[args.to]
    policy = BUILTIN_POLICIES[args.policy]
    output_dir = Path(args.output)

    identity = None
    store_dir = Path(args.store_dir)
    id_path = store_dir / "identity.json"
    if id_path.exists():
        from cortex.versioning.upai.identity import UPAIIdentity

        identity = UPAIIdentity.load(store_dir)

    paths = adapter.push(graph, policy, identity=identity, output_dir=output_dir)

    if ctx.cli_quiet:
        return 0
    ctx.echo(f"Synced to {args.to} with policy '{args.policy}':")
    for item in paths:
        ctx.echo(f"  {item}")
    return 0


def run_verify(args, *, ctx: PortableCliContext) -> int:  # noqa: ARG001 - ctx reserved for future consistency
    """Verify a signed export file."""
    from cortex.versioning.upai.identity import UPAIIdentity

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {input_path}: {exc}")
        return 1

    if not isinstance(data, dict) or "upai_identity" not in data:
        print("Not a UPAI-signed file (no upai_identity block).")
        return 1

    payload = json.dumps(data["data"], sort_keys=True, ensure_ascii=False).encode("utf-8")
    import hashlib

    computed_hash = hashlib.sha256(payload).hexdigest()
    stored_hash = data.get("integrity_hash", "")

    if computed_hash == stored_hash:
        print("Integrity: PASS (SHA-256 matches)")
    else:
        print("Integrity: FAIL (SHA-256 mismatch)")
        return 1

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


def run_gaps(args, *, ctx: PortableCliContext) -> int:
    """Analyze gaps in the knowledge graph."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    from cortex.intelligence import GapAnalyzer

    graph = ctx.load_graph(input_path)
    analyzer = GapAnalyzer()
    gaps = analyzer.all_gaps(graph)

    if gaps["category_gaps"]:
        print(f"Missing categories ({len(gaps['category_gaps'])}):")
        for gap in gaps["category_gaps"]:
            print(f"  - {gap['category']}")

    if gaps["confidence_gaps"]:
        print(f"\nLow-confidence priorities ({len(gaps['confidence_gaps'])}):")
        for gap in gaps["confidence_gaps"]:
            print(f"  - {gap['label']} (conf={gap['confidence']:.2f})")

    if gaps["relationship_gaps"]:
        print(f"\nUnconnected groups ({len(gaps['relationship_gaps'])}):")
        for gap in gaps["relationship_gaps"]:
            print(f"  - {gap['tag']}: {gap['node_count']} nodes, 0 edges")

    if gaps["temporal_gaps"]:
        print(f"\nTemporal gaps ({len(gaps['temporal_gaps'])}):")
        for gap in gaps["temporal_gaps"]:
            suffix = f" [{gap['status']}]" if gap.get("status") else ""
            print(f"  - {gap['label']}: {gap['kind']}{suffix}")

    if gaps["isolated_nodes"]:
        print(f"\nIsolated nodes ({len(gaps['isolated_nodes'])}):")
        for gap in gaps["isolated_nodes"]:
            print(f"  - {gap['label']} (conf={gap['confidence']:.2f})")

    if gaps["stale_nodes"]:
        print(f"\nStale nodes ({len(gaps['stale_nodes'])}):")
        for gap in gaps["stale_nodes"]:
            print(f"  - {gap['label']} (last seen: {gap['last_seen']})")

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


def run_digest(args, *, ctx: PortableCliContext) -> int:
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

    current = ctx.load_graph(input_path)
    previous = ctx.load_graph(previous_path)
    generator = InsightGenerator()
    digest = generator.digest(current=current, previous=previous)

    if digest["new_nodes"]:
        print(f"New nodes ({len(digest['new_nodes'])}):")
        for node in digest["new_nodes"]:
            print(f"  + {node['label']} (conf={node['confidence']:.2f})")

    if digest["removed_nodes"]:
        print(f"\nRemoved nodes ({len(digest['removed_nodes'])}):")
        for node in digest["removed_nodes"]:
            print(f"  - {node['label']}")

    if digest["confidence_changes"]:
        print(f"\nConfidence changes ({len(digest['confidence_changes'])}):")
        for change in digest["confidence_changes"]:
            direction = "+" if change["delta"] > 0 else ""
            print(
                f"  {change['label']}: {change['previous']:.2f} -> {change['current']:.2f} "
                f"({direction}{change['delta']:.2f})"
            )

    if digest["temporal_changes"]:
        print(f"\nTemporal changes ({len(digest['temporal_changes'])}):")
        for change in digest["temporal_changes"]:
            print(
                f"  {change['label']}: "
                f"status {change['previous_status'] or '?'} -> {change['current_status'] or '?'}; "
                f"valid_from {change['previous_valid_from'] or '?'} -> {change['current_valid_from'] or '?'}; "
                f"valid_to {change['previous_valid_to'] or '?'} -> {change['current_valid_to'] or '?'}"
            )

    if digest["new_edges"]:
        print(f"\nNew edges ({len(digest['new_edges'])}):")
        for edge in digest["new_edges"]:
            print(f"  {edge['source']} --[{edge['relation']}]--> {edge['target']}")

    drift_score = digest["drift_score"]
    if drift_score.get("sufficient_data"):
        print(f"\nDrift score: {drift_score['score']:.4f}")
    else:
        print("\nDrift score: insufficient data")

    if digest["new_contradictions"]:
        print(f"\nContradictions ({len(digest['new_contradictions'])}):")
        for contradiction in digest["new_contradictions"]:
            print(f"  [{contradiction['type']}] {contradiction['description']}")

    gap_count = sum(len(value) for value in digest["gaps"].values() if isinstance(value, list))
    print(f"\nGaps: {gap_count} total issues")
    return 0


def run_viz(args, *, ctx: PortableCliContext) -> int:
    """Render graph visualization as HTML or SVG."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    from cortex.viz.layout import fruchterman_reingold
    from cortex.viz.renderer import render_html, render_svg

    graph = ctx.load_graph(input_path)

    def progress(current, total):
        print(f"\rLayout: {current}/{total}", end="", flush=True)

    layout = fruchterman_reingold(
        graph,
        iterations=args.iterations,
        max_nodes=args.max_nodes,
        progress=progress,
    )
    print()

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


def run_watch(args, *, ctx: PortableCliContext) -> int:  # noqa: ARG001 - ctx reserved for future consistency
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


def run_sync_schedule(args, *, ctx: PortableCliContext) -> int:  # noqa: ARG001 - ctx reserved for future consistency
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
                print(f"  {platform}: {', '.join(str(path) for path in paths)}")
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


def run_extract_coding(args, *, ctx: PortableCliContext) -> int:
    """Extract identity signals from coding tool sessions."""
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
        input_path = Path(args.input_file)
        if not input_path.exists():
            print(f"File not found: {input_path}")
            return 1
        session_paths = [input_path]
    else:
        print("Provide an input file or use --discover")
        return 1

    sessions = []
    for session_path in session_paths:
        if args.verbose:
            print(f"  Parsing: {session_path.name}")
        records = load_claude_code_session(session_path)
        session = parse_claude_code_session(records)
        sessions.append(session)

    combined = aggregate_sessions(sessions) if len(sessions) > 1 else sessions[0]

    if getattr(args, "enrich", False) and combined.project_path:
        from cortex.coding import enrich_session

        enrich_session(combined)

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
            project_meta = combined.project_meta
            print(f"  Project:      {project_meta.name}")
            if project_meta.description:
                print(f"  Description:  {project_meta.description[:100]}")
            if project_meta.license:
                print(f"  License:      {project_meta.license}")
            if project_meta.manifest_file:
                print(f"  Manifest:     {project_meta.manifest_file}")

    ctx_data = session_to_context(combined)

    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            with open(merge_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            for category, topics in existing.get("categories", {}).items():
                if category not in ctx_data.setdefault("categories", {}):
                    ctx_data["categories"][category] = []
                existing_keys = {topic.get("topic", "").lower() for topic in ctx_data["categories"][category]}
                for topic in topics:
                    if topic.get("topic", "").lower() not in existing_keys:
                        ctx_data["categories"][category].append(topic)
            if args.verbose:
                print(f"\nMerged with {merge_path}")

    output_path = Path(args.output) if args.output else Path("coding_context.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(ctx_data, handle, indent=2, default=str)
    print(f"\nOutput: {output_path}")

    cat_counts = {name: len(items) for name, items in ctx_data.get("categories", {}).items() if items}
    if cat_counts:
        print(f"Extracted: {cat_counts}")

    return 0


def run_context_hook(args, *, ctx: PortableCliContext) -> int:  # noqa: ARG001 - ctx reserved for future consistency
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

    if args.action == "uninstall":
        removed = uninstall_hook()
        if removed:
            print("Cortex hook uninstalled.")
            print("Restart Claude Code to apply changes.")
        else:
            print("No Cortex hook found to remove.")
        return 0

    if args.action == "test":
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

    if args.action == "status":
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


def run_context_export(args, *, ctx: PortableCliContext) -> int:  # noqa: ARG001 - ctx reserved for future consistency
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


def run_context_write(args, *, ctx: PortableCliContext) -> int:  # noqa: ARG001 - ctx reserved for future consistency
    """Write identity context to AI coding tool config files."""
    from cortex.portability.context import CONTEXT_TARGETS, resolve_context_targets, watch_and_refresh, write_context

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


def run_mount(args, *, ctx: PortableCliContext) -> int:  # noqa: ARG001 - ctx reserved for future consistency
    """Manage mounted context runtime files."""
    if args.mount_subcommand != "watch":
        print("Specify a mount subcommand. Try: cortex mount watch --project .")
        return 1

    import signal
    import threading

    from cortex.portability.context import CONTEXT_TARGETS, resolve_context_targets, watch_and_refresh
    from cortex.portability.portable_state import default_graph_path

    project_dir = Path(args.project or ".").expanduser().resolve()
    store_dir = Path(args.store_dir).expanduser()
    if not store_dir.is_absolute():
        store_dir = project_dir / store_dir

    if args.graph:
        graph_path = Path(args.graph).expanduser()
        if not graph_path.is_absolute():
            graph_path = project_dir / graph_path
        graph_path = graph_path.resolve()
    else:
        graph_path = default_graph_path(store_dir)

    if not graph_path.exists():
        print(f"File not found: {graph_path}")
        return 1

    try:
        platforms = resolve_context_targets(args.to)
    except ValueError as exc:
        print(str(exc))
        print(f"Available: {', '.join(CONTEXT_TARGETS.keys())}, all")
        return 1

    stop_event = threading.Event()
    previous_handler = None
    installed_handler = False

    def _handle_sigint(_signum, _frame) -> None:
        stop_event.set()
        print("\nStopping mount watcher...")

    if threading.current_thread() is threading.main_thread():
        previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _handle_sigint)
        installed_handler = True

    try:
        watch_and_refresh(
            graph_path=str(graph_path),
            platforms=platforms,
            project_dir=str(project_dir),
            policy=args.policy,
            max_chars=args.max_chars,
            interval=args.interval,
            stop_event=stop_event,
        )
    finally:
        if installed_handler:
            signal.signal(signal.SIGINT, previous_handler)

    return 0


def run_portable(args, *, ctx: PortableCliContext) -> int:
    """One-command portability flow: load or extract context, then install it across tools."""
    from cortex.graph.minds import (
        adopt_graph_into_mind,
        load_mind_core_graph,
        resolve_default_mind,
        sync_mind_compatibility_targets,
    )
    from cortex.hooks import _load_graph as load_graph_optional
    from cortex.portability.portability import resolve_portable_targets
    from cortex.portability.portable_runtime import (
        merge_graphs,
        save_canonical_graph,
        sync_targets,
    )

    ctx.emit_compatibility_note(
        "portable",
        "cortex mind ingest <mind> --from-detected ...",
        note="Use `cortex sync` when you only need to refresh already-ingested runtime context.",
        format_name=getattr(args, "format", None),
    )

    detected_selection = list(getattr(args, "from_detected", []) or [])
    project_dir = Path(args.project) if args.project else Path.cwd()
    detected_payload: dict[str, Any] | None = None

    if detected_selection and args.input_file:
        return ctx.error("Use either an input file or `--from-detected`, not both.")
    if not detected_selection and not args.input_file:
        return ctx.error("Provide an export file or use `--from-detected`.")

    try:
        targets = resolve_portable_targets(args.to)
    except ValueError as exc:
        return ctx.error(str(exc))

    input_path: Path | None = None
    graph: CortexGraph | None = None
    detected_kind = "detected" if detected_selection else "graph"
    extracted_stats = None
    try:
        redactor = ctx.build_pii_redactor(
            args,
            default_enabled=bool(detected_selection and not getattr(args, "no_redact_detected", False)),
        )
    except FileNotFoundError as exc:
        return ctx.missing_path_error(Path(exc.args[0]), label="Redaction patterns file")

    if redactor is not None and args.format != "json":
        if detected_selection and not args.redact:
            ctx.echo("PII redaction enabled for detected local sources")
        else:
            ctx.echo("PII redaction enabled")

    if detected_selection:
        try:
            detected_payload = ctx.load_detected_sources_or_error(
                args,
                project_dir=project_dir,
                announce=args.format != "json" and not ctx.cli_quiet,
                redactor=redactor,
            )
        except ValueError as exc:
            lines = str(exc).splitlines()
            return ctx.error(lines[0], hint="\n".join(lines[1:]) or None)
        graph = detected_payload["graph"]
        input_path = project_dir / "detected_sources.json"
        extracted_stats = ctx.graph_category_stats(graph)
        if args.format != "json":
            ctx.echo(
                f"Detected sources: {len(detected_payload['selected_sources'])} selected, "
                f"{len(detected_payload['skipped_sources'])} skipped"
            )
    else:
        input_path = Path(args.input_file)
        if not input_path.exists():
            return ctx.missing_path_error(input_path, label="Input file")
        graph = load_graph_optional(str(input_path))

    if graph is None and input_path is not None:
        try:
            data, detected_format = load_file(input_path)
        except PermissionError:
            return ctx.permission_error(input_path, action="read the input file")
        except Exception as exc:  # pragma: no cover
            return ctx.error(str(exc))

        fmt = args.input_format if args.input_format != "auto" else detected_format
        extractor = AggressiveExtractor(redactor=redactor)
        v4_data = ctx.run_extraction(extractor, data, fmt)
        graph = upgrade_v4_to_v5(v4_data)
        detected_kind = fmt
        extracted_stats = extractor.context.stats()

    output_dir = Path(args.output)
    store_dir = Path(args.store_dir)
    try:
        default_mind = resolve_default_mind(store_dir)
    except (FileNotFoundError, ValueError) as exc:
        return ctx.error(str(exc))

    identity = None
    identity_path = store_dir / "identity.json"
    if identity_path.exists():
        from cortex.versioning.upai.identity import UPAIIdentity

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
            return ctx.permission_error(output_dir, action="write portability files")
        except OSError as exc:
            return ctx.error(f"Could not write portability files into {output_dir}: {exc}")
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
                return ctx.permission_error(output_dir, action="write portability files")
            except OSError as exc:
                return ctx.error(f"Could not write portability files into {output_dir}: {exc}")
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
    if ctx.emit_result(payload, args.format) == 0:
        return 0

    ctx.echo("Portable context ready:")
    if default_mind:
        ctx.echo(f"  default Mind: {default_mind}")
    ctx.echo(f"  context: {graph_path_for_installs}" + (" (dry-run)" if args.dry_run else ""))
    ctx.echo(f"  source: {detected_kind}")
    if extracted_stats is not None:
        ctx.echo(
            f"  extracted: {extracted_stats['total']} topics across {len(extracted_stats['by_category'])} categories"
        )

    if payload["targets"]:
        ctx.echo("\nTargets:")
        for result in payload["targets"]:
            joined = ", ".join(result["paths"]) if result["paths"] else "(no files)"
            ctx.echo(f"  {result['target']}: {joined} [{result['status']}]")
            if result.get("note"):
                ctx.echo(f"    {result['note']}")

    return 0


__all__ = [
    "PortableCliContext",
    "run_context_export",
    "run_context_hook",
    "run_context_write",
    "run_digest",
    "run_extract_coding",
    "run_gaps",
    "run_mount",
    "run_portable",
    "run_sync",
    "run_sync_schedule",
    "run_verify",
    "run_viz",
    "run_watch",
]
