#!/usr/bin/env python3
"""Graph, history, and governance command handlers for the Cortex CLI."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from cortex import cli_graph_version_commands as cli_graph_version_commands_module
from cortex import cli_parser as cli_parser_module
from cortex.compat import upgrade_v4_to_v5
from cortex.graph.contradictions import ContradictionEngine
from cortex.graph.graph import CortexGraph, Node

if TYPE_CHECKING:
    from cortex.graph.claims import ClaimEvent
    from cortex.versioning.upai.identity import UPAIIdentity


@dataclass(frozen=True)
class GraphCliContext:
    """Callbacks supplied by the main CLI module."""

    emit_result: Callable[[Any, str], int]
    echo: Callable[..., None]
    error: Callable[..., int]
    missing_path_error: Callable[..., int]


GOVERNANCE_ACTION_CHOICES = cli_parser_module.GOVERNANCE_ACTION_CHOICES


def _graph_version_cli_context(ctx: GraphCliContext) -> cli_graph_version_commands_module.GraphVersionCliContext:
    return cli_graph_version_commands_module.GraphVersionCliContext(
        emit_result=ctx.emit_result,
        current_branch_or_ref=_current_branch_or_ref,
        governance_decision_or_error=_governance_decision_or_error,
        load_graph=_load_graph,
        load_identity=_load_identity,
        maybe_commit_graph=_maybe_commit_graph,
        save_graph=_save_graph,
    )


def run_query(args, *, ctx: GraphCliContext):
    """Query nodes/neighbors in a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        return ctx.missing_path_error(input_path, label="Context file")

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
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            ctx.echo(f"No node found with label '{args.node}'")
            return 0
        for node in nodes:
            ctx.echo(f"Node: {node.label} (id={node.id})")
            ctx.echo(f"  Tags: {', '.join(node.tags)}")
            ctx.echo(f"  Confidence: {node.confidence:.2f}")
            ctx.echo(f"  Mentions: {node.mention_count}")
            if getattr(node, "status", ""):
                ctx.echo(f"  Status: {node.status}")
            if getattr(node, "valid_from", "") or getattr(node, "valid_to", ""):
                ctx.echo(f"  Valid: {getattr(node, 'valid_from', '') or '?'} -> {getattr(node, 'valid_to', '') or '?'}")
            if node.brief:
                ctx.echo(f"  Brief: {node.brief}")
            if node.full_description:
                ctx.echo(f"  Description: {node.full_description}")
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
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            ctx.echo(f"No node found with label '{args.neighbors}'")
            return 0
        node = nodes[0]
        neighbors = graph.get_neighbors(node.id)
        if not neighbors:
            ctx.echo(f"No neighbors for '{node.label}'")
            return 0
        ctx.echo(f"Neighbors of '{node.label}':")
        for edge, neighbor in neighbors:
            ctx.echo(f"  --[{edge.relation}]--> {neighbor.label} (conf={neighbor.confidence:.2f})")
        return 0

    # --- Phase 5 queries (QueryEngine) ---
    from cortex.graph.query import (
        QueryEngine,
        connected_components,
        parse_nl_query,
    )
    from cortex.graph.query_lang import execute_query
    from cortex.intelligence import GapAnalyzer

    engine = QueryEngine(graph)

    if args.category:
        nodes = engine.query_category(args.category)
        payload = {
            "status": "ok",
            "query": "category",
            "tag": args.category,
            "nodes": [_node_payload(node) for node in nodes],
        }
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            ctx.echo(f"No nodes with tag '{args.category}'")
            return 0
        ctx.echo(f"Nodes tagged '{args.category}' ({len(nodes)}):")
        for node in nodes:
            ctx.echo(f"  {node.label} (conf={node.confidence:.2f})")
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
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not paths:
            ctx.echo(f"No path from '{from_label}' to '{to_label}'")
            return 0
        ctx.echo(f"Path from '{from_label}' to '{to_label}':")
        for node in paths[0]:
            ctx.echo(f"  -> {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.changed_since:
        result = engine.query_changed(args.changed_since)
        if ctx.emit_result(result, args.format) == 0:
            return 0
        ctx.echo(f"Changes since {result['since']}: {result['total_changed']} total")
        if result["new_nodes"]:
            ctx.echo(f"\nNew ({len(result['new_nodes'])}):")
            for n in result["new_nodes"]:
                ctx.echo(f"  + {n['label']} (conf={n['confidence']:.2f})")
        if result["updated_nodes"]:
            ctx.echo(f"\nUpdated ({len(result['updated_nodes'])}):")
            for n in result["updated_nodes"]:
                ctx.echo(f"  ~ {n['label']} (conf={n['confidence']:.2f})")
        return 0

    if args.strongest:
        nodes = engine.query_strongest(args.strongest)
        payload = {"status": "ok", "query": "strongest", "nodes": [_node_payload(node) for node in nodes]}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Top {len(nodes)} by confidence:")
        for node in nodes:
            ctx.echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.weakest:
        nodes = engine.query_weakest(args.weakest)
        payload = {"status": "ok", "query": "weakest", "nodes": [_node_payload(node) for node in nodes]}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        ctx.echo(f"Bottom {len(nodes)} by confidence:")
        for node in nodes:
            ctx.echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.isolated:
        analyzer = GapAnalyzer()
        isolated = analyzer.isolated_nodes(graph)
        payload = {"status": "ok", "query": "isolated", "nodes": [_node_payload(node) for node in isolated]}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not isolated:
            ctx.echo("No isolated nodes.")
            return 0
        ctx.echo(f"Isolated nodes ({len(isolated)}):")
        for node in isolated:
            ctx.echo(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.related is not None:
        if not args.related:
            return ctx.error("Specify a label for --related.", hint="Usage: cortex query <file> --related <LABEL>")
        nodes = engine.query_related(args.related, depth=args.related_depth)
        payload = {
            "status": "ok",
            "query": "related",
            "label": args.related,
            "depth": args.related_depth,
            "nodes": [_node_payload(node) for node in nodes],
        }
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not nodes:
            ctx.echo(f"No related nodes for '{args.related}'")
            return 0
        ctx.echo(f"Related to '{args.related}' (depth={args.related_depth}):")
        for node in nodes:
            ctx.echo(f"  {node.label} (conf={node.confidence:.2f})")
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
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not comps:
            ctx.echo("No components (empty graph).")
            return 0
        ctx.echo(f"Connected components ({len(comps)}):")
        for i, comp in enumerate(comps, 1):
            labels = sorted(graph.get_node(nid).label for nid in comp if graph.get_node(nid))
            ctx.echo(f"  {i}. [{len(comp)} nodes] {', '.join(labels[:10])}{'...' if len(labels) > 10 else ''}")
        return 0

    if args.search:
        results = graph.semantic_search(args.search, limit=args.limit)
        payload = {
            "status": "ok",
            "query": "search",
            "search": args.search,
            "results": [{"score": item["score"], "node": item["node"].to_dict()} for item in results],
        }
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not results:
            ctx.echo(f"No search results for '{args.search}'")
            return 0
        ctx.echo(f"Search results for '{args.search}' ({len(results)}):")
        for item in results:
            node = item["node"]
            aliases = f" | aliases: {', '.join(node.aliases)}" if getattr(node, "aliases", []) else ""
            ctx.echo(f"  {node.label} (score={item['score']:.4f}, conf={node.confidence:.2f}){aliases}")
        return 0

    if args.dsl:
        result = execute_query(graph, args.dsl)
        if result.get("type") == "search" and args.limit and len(result.get("results", [])) > args.limit:
            result["results"] = result["results"][: args.limit]
            result["count"] = len(result["results"])
        if ctx.emit_result(result, args.format) == 0:
            return 0
        ctx.echo(json.dumps(result, indent=2, default=str))
        return 0

    if args.nl:
        result = parse_nl_query(args.nl, engine)
        if ctx.emit_result(result, args.format) == 0:
            return 0
        ctx.echo(json.dumps(result, indent=2, default=str))
        return 0

    return ctx.error(
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
    from cortex.versioning.upai.identity import UPAIIdentity

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
    from cortex.graph.claims import ClaimEvent

    if record is None:
        return None
    if isinstance(record, ClaimEvent):
        return record
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    return ClaimEvent.from_dict(payload)


def run_timeline(args, *, ctx: GraphCliContext):
    """Generate a timeline from a context/graph file."""
    if args.input_file == "review":
        from cortex.graph.minds import load_mind_core_graph
        from cortex.graph.temporal import TEMPORAL_REVIEW_QUEUE_KEY

        if not args.mind:
            return ctx.error("`cortex timeline review` requires --mind <id>.")
        try:
            payload = load_mind_core_graph(Path(args.store_dir), args.mind)
        except (FileNotFoundError, ValueError) as exc:
            return ctx.error(str(exc))
        queue = [
            dict(item)
            for item in payload["graph"].meta.get(TEMPORAL_REVIEW_QUEUE_KEY, [])
            if float(item.get("temporal_confidence", 0.0) or 0.0) < float(args.min_confidence)
        ]
        result = {
            "status": "ok",
            "mind": args.mind,
            "graph_ref": payload.get("graph_ref", ""),
            "threshold": float(args.min_confidence),
            "queue_count": len(queue),
            "queued_facts": queue,
        }
        if ctx.emit_result(result, "json") == 0 and getattr(args, "json_output", False):
            return 0
        if not queue:
            print(f"No pending temporal review items for Mind `{args.mind}` below {args.min_confidence:.2f}.")
            return 0
        print(f"Temporal review queue for Mind `{args.mind}` ({len(queue)} item(s))")
        for item in queue:
            print(
                f"  - {item['label']} [{item.get('temporal_signal', 'unknown')}] "
                f"confidence={float(item.get('temporal_confidence', 0.0)):.2f}"
            )
        return 0

    from cortex.timeline import TimelineGenerator

    if not args.input_file:
        return ctx.error("Provide a context file or use `cortex timeline review --mind <id>`.")
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


def run_memory_conflicts(args, *, ctx: GraphCliContext):
    from cortex.memory_ops import list_memory_conflicts

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    conflicts = [item.to_dict() for item in list_memory_conflicts(graph, min_severity=args.severity)]
    if ctx.emit_result({"conflicts": conflicts}, args.format) == 0:
        return 0
    if not conflicts:
        print("No memory conflicts.")
        return 0
    print(f"Found {len(conflicts)} memory conflict(s):")
    for conflict in conflicts:
        print(f"  {conflict['id']} [{conflict['type']}] severity={conflict['severity']:.2f}")
        print(f"    {conflict['summary']}")
    return 0


def run_memory_show(args, *, ctx: GraphCliContext):
    from cortex.memory_ops import show_memory_nodes

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)
    nodes = show_memory_nodes(graph, label=args.label, tag=args.tag, limit=args.limit)
    if ctx.emit_result({"nodes": nodes}, args.format) == 0:
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


def run_memory_forget(args, *, ctx: GraphCliContext):
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
    if ctx.emit_result(result, args.format) == 0:
        return 0
    print(f"Removed {result['nodes_removed']} node(s).")
    return 0


def run_memory_set(args, *, ctx: GraphCliContext):
    from cortex.graph.claims import ClaimEvent
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
    if ctx.emit_result(result, args.format) == 0:
        return 0
    print(f"{'Created' if result['created'] else 'Updated'} node {result['node_id']}.")
    return 0


def run_memory_retract(args, *, ctx: GraphCliContext):
    from cortex.graph.claims import ClaimEvent
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
    if ctx.emit_result(result, args.format) == 0:
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


def run_blame(args, *, ctx: GraphCliContext):
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
    if ctx.emit_result(result, args.format) == 0:
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


def run_history(args, *, ctx: GraphCliContext):
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
    if ctx.emit_result(payload, args.format) == 0:
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


def run_claim_accept(args, *, ctx: GraphCliContext):
    from cortex.graph.claims import ClaimEvent, claim_event_to_node

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
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    print(f"Accepted claim {args.claim_id} for node {node.label}.")
    return 0


def run_claim_reject(args, *, ctx: GraphCliContext):
    from cortex.graph.claims import ClaimEvent

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
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    print(f"Rejected claim {args.claim_id}.")
    return 0


def run_claim_supersede(args, *, ctx: GraphCliContext):
    from cortex.graph.claims import ClaimEvent, claim_event_to_node

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
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    print(f"Superseded claim {args.claim_id} with {new_assert.claim_id}.")
    return 0


def run_claim_log(args, *, ctx: GraphCliContext):
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
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    if not events:
        print("No claim events found.")
        return 0
    print(f"Claim events ({len(events)}):")
    for event in events:
        version = event.version_id[:8] if event.version_id else "local"
        print(f"  {event.timestamp} [{event.op}] {event.label} source={event.source or '-'} version={version}")
    return 0


def run_claim_show(args, *, ctx: GraphCliContext):
    from cortex.storage import get_storage_backend

    ledger = get_storage_backend(Path(args.store_dir)).claims
    events = ledger.get_claim(args.claim_id)
    payload = {"claim_id": args.claim_id, "events": [event.to_dict() for event in events]}
    if ctx.emit_result(payload, args.format) == 0:
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


def run_memory_resolve(args, *, ctx: GraphCliContext):
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
    if ctx.emit_result(result, args.format) == 0:
        return 0
    if result.get("status") != "ok":
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1
    print(f"Resolved {result['conflict_id']} with action {result['action']}.")
    return 0


def run_contradictions(args, *, ctx: GraphCliContext):
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


def run_drift(args, *, ctx: GraphCliContext):
    """Compute identity drift between two graph files."""
    from cortex.graph.temporal import drift_score

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


_resolve_version_or_exit = cli_graph_version_commands_module._resolve_version_or_exit
_resolve_version_at_or_exit = cli_graph_version_commands_module._resolve_version_at_or_exit
_rule_from_args = cli_graph_version_commands_module._rule_from_args


def run_diff(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_diff(args, ctx=_graph_version_cli_context(ctx))


def run_integrity(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_integrity(args, ctx=_graph_version_cli_context(ctx))


def run_checkout(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_checkout(args, ctx=_graph_version_cli_context(ctx))


def run_rollback(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_rollback(args, ctx=_graph_version_cli_context(ctx))


def run_identity(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_identity(args, ctx=_graph_version_cli_context(ctx))


def run_commit(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_commit(args, ctx=_graph_version_cli_context(ctx))


def run_branch(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_branch(args, ctx=_graph_version_cli_context(ctx))


def run_switch(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_switch(args, ctx=_graph_version_cli_context(ctx))


def run_merge(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_merge(args, ctx=_graph_version_cli_context(ctx))


def run_review(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_review(args, ctx=_graph_version_cli_context(ctx))


def run_log(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_log(args, ctx=_graph_version_cli_context(ctx))


def run_governance(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_governance(args, ctx=_graph_version_cli_context(ctx))


def run_remote(args, *, ctx: GraphCliContext):
    return cli_graph_version_commands_module.run_remote(args, ctx=_graph_version_cli_context(ctx))


__all__ = [
    "GraphCliContext",
    "_claim_event_from_record",
    "_current_branch_or_ref",
    "_find_claim_target_node",
    "_governance_decision_or_error",
    "_load_claim_or_error",
    "_load_graph",
    "_load_identity",
    "_maybe_commit_graph",
    "_parse_properties",
    "_resolve_version_at_or_exit",
    "_resolve_version_or_exit",
    "_rule_from_args",
    "_save_graph",
    "run_blame",
    "run_branch",
    "run_checkout",
    "run_claim_accept",
    "run_claim_log",
    "run_claim_reject",
    "run_claim_show",
    "run_claim_supersede",
    "run_commit",
    "run_contradictions",
    "run_diff",
    "run_drift",
    "run_governance",
    "run_history",
    "run_identity",
    "run_log",
    "run_memory_conflicts",
    "run_memory_forget",
    "run_memory_resolve",
    "run_memory_retract",
    "run_memory_set",
    "run_memory_show",
    "run_merge",
    "run_query",
    "run_remote",
    "run_review",
    "run_rollback",
    "run_switch",
    "run_timeline",
]
