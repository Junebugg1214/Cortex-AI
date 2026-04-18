#!/usr/bin/env python3
"""Miscellaneous command handlers for the Cortex CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cortex.adapters import ADAPTERS
from cortex.compat import upgrade_v4_to_v5
from cortex.graph import CortexGraph


@dataclass(frozen=True)
class MiscCliContext:
    """Callbacks supplied by the main CLI module."""

    build_parser: Callable[[], Any]
    echo: Callable[..., None]
    error: Callable[..., int]
    missing_path_error: Callable[..., int]


def run_stats(args, *, ctx: MiscCliContext) -> int:
    """Show statistics for a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        return ctx.missing_path_error(input_path)

    with input_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    version = data.get("schema_version", "")
    if version.startswith("5"):
        graph = CortexGraph.from_v5_json(data)
    else:
        graph = upgrade_v4_to_v5(data)

    stats = graph.stats()
    ctx.echo(f"Nodes: {stats['node_count']}")
    ctx.echo(f"Edges: {stats['edge_count']}")
    ctx.echo(f"Avg degree: {stats['avg_degree']}")
    if stats.get("isolated_nodes", 0) > 0:
        ctx.echo(f"Isolated nodes (0 edges): {stats['isolated_nodes']}")
    if stats["tag_distribution"]:
        ctx.echo("Tag distribution:")
        for tag, count in sorted(stats["tag_distribution"].items(), key=lambda item: -item[1]):
            ctx.echo(f"  {tag}: {count}")
    if stats.get("relation_distribution"):
        ctx.echo("Relation distribution:")
        for rel, count in sorted(stats["relation_distribution"].items(), key=lambda item: -item[1]):
            ctx.echo(f"  {rel}: {count}")
    if stats.get("top_central_nodes"):
        ctx.echo(f"Top central nodes: {', '.join(stats['top_central_nodes'])}")
    return 0


def run_extractions_tail(args, *, ctx: MiscCliContext) -> int:
    """Show recent extraction diagnostics records."""

    from cortex.extraction.diagnostics import format_extraction_records, tail_extraction_records

    records = tail_extraction_records(limit=max(int(args.limit), 0))
    ctx.echo(format_extraction_records(records))
    return 0


def run_pull(args, *, ctx: MiscCliContext) -> int:
    """Import a platform export file back into a CortexGraph."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        return ctx.missing_path_error(input_path)

    adapter = ADAPTERS.get(args.from_platform)
    if adapter is None:
        return ctx.error(f"Unknown platform: {args.from_platform}")

    try:
        graph = adapter.pull(input_path)
    except Exception as exc:
        return ctx.error(f"Error parsing {input_path}: {exc}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_graph.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")

    stats = graph.stats()
    ctx.echo(f"Imported from {args.from_platform}: {stats['node_count']} nodes, {stats['edge_count']} edges")
    ctx.echo(f"Saved to: {output_path}")
    return 0


def run_rotate(args, *, ctx: MiscCliContext) -> int:
    """Rotate UPAI identity key."""
    from cortex.upai.identity import UPAIIdentity
    from cortex.upai.keychain import Keychain

    store_dir = Path(args.store_dir)
    if not (store_dir / "identity.json").exists():
        return ctx.error(f"No identity found in {store_dir}. Run: cortex identity --init")

    identity = UPAIIdentity.load(store_dir)
    keychain = Keychain(store_dir)

    new_identity, proof = keychain.rotate(identity, reason=args.reason)
    ctx.echo(f"Old DID: {identity.did}")
    ctx.echo(f"New DID: {new_identity.did}")
    ctx.echo(f"Reason: {args.reason}")
    if proof:
        ctx.echo(f"Revocation proof: {proof[:32]}...")
    ctx.echo("Identity rotated successfully.")
    return 0


def run_completion(args, *, ctx: MiscCliContext) -> int:
    """Generate shell completion script."""
    from cortex.completion import generate_completion

    parser = ctx.build_parser()
    script = generate_completion(parser, args.shell)
    ctx.echo(script, force=True)
    return 0
