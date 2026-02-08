#!/usr/bin/env python3
"""
Unified migration tool: chains extract + import in a single command.

Usage:
    # Full pipeline (default when first arg is a file)
    python migrate.py chatgpt-export.zip --to claude
    python migrate.py export.zip --to all -o ./output --redact --verbose

    # Extract only
    python migrate.py extract chatgpt-export.zip -o context.json

    # Import only
    python migrate.py import context.json --to notion -o ./output
"""

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup – import from both skill scripts
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "skills" / "chatbot-memory-extractor" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "chatbot-memory-importer" / "scripts"))

from extract_memory import (
    AggressiveExtractor, load_file, merge_contexts, PIIRedactor,
)
from import_memory import (
    NormalizedContext, CONFIDENCE_THRESHOLDS,
    export_claude_preferences, export_claude_memories,
    export_system_prompt, export_notion, export_notion_database_json,
    export_google_docs, export_summary, export_full_json,
)

# Cortex graph imports (Phase 1)
sys.path.insert(0, str(_ROOT))
from cortex.graph import CortexGraph
from cortex.compat import upgrade_v4_to_v5, downgrade_v5_to_v4

# ---------------------------------------------------------------------------
# Platform → format-key mapping
# ---------------------------------------------------------------------------
PLATFORM_FORMATS = {
    "claude":        ["claude-preferences", "claude-memories"],
    "notion":        ["notion", "notion-db"],
    "gdocs":         ["gdocs"],
    "system-prompt": ["system-prompt"],
    "summary":       ["summary"],
    "full":          ["full"],
    "all": [
        "claude-preferences", "claude-memories", "system-prompt",
        "notion", "notion-db", "gdocs", "summary", "full",
    ],
}

# ---------------------------------------------------------------------------
# Export dispatch table: format-key → (export_fn, filename, is_json)
# ---------------------------------------------------------------------------
EXPORT_DISPATCH = {
    "claude-preferences": (export_claude_preferences, "claude_preferences.txt",   False),
    "claude-memories":    (export_claude_memories,     "claude_memories.json",     True),
    "system-prompt":      (export_system_prompt,       "system_prompt.txt",        False),
    "notion":             (export_notion,              "notion_page.md",           False),
    "notion-db":          (export_notion_database_json,"notion_database.json",     True),
    "gdocs":              (export_google_docs,         "google_docs.html",         False),
    "summary":            (export_summary,             "summary.md",              False),
    "full":               (export_full_json,           "full_export.json",         True),
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_extraction(extractor, data, fmt):
    """Route *data* through the correct extractor method and return the v4 dict."""
    if fmt == "openai":
        extractor.process_openai_export(data)
    elif fmt == "gemini":
        extractor.process_gemini_export(data)
    elif fmt == "perplexity":
        extractor.process_perplexity_export(data)
    elif fmt == "jsonl":
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
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for key in format_keys:
        export_fn, filename, is_json = EXPORT_DISPATCH[key]
        path = output_dir / filename
        result = export_fn(ctx, min_conf)
        if is_json:
            path.write_text(json.dumps(result, indent=2))
        else:
            path.write_text(result)
        outputs.append((key, path))
        if verbose:
            print(f"   wrote {path}")
    return outputs


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="migrate",
        description="Unified chatbot-memory migration: extract + import in one step.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # -- migrate (default) --------------------------------------------------
    mig = sub.add_parser("migrate", help="Full pipeline: extract then import")
    mig.add_argument("input_file", help="Path to chat export file")
    mig.add_argument("--to", "-t", dest="to", default="all",
                     choices=list(PLATFORM_FORMATS.keys()),
                     help="Target platform shortcut (default: all)")
    mig.add_argument("--output", "-o", default="./output", help="Output directory")
    mig.add_argument("--input-format", "-F",
                     choices=["auto", "openai", "gemini", "perplexity",
                              "jsonl", "api_logs", "messages", "text", "generic"],
                     default="auto", help="Override input format auto-detection")
    mig.add_argument("--merge", "-m", help="Existing context file to merge with")
    mig.add_argument("--redact", action="store_true", help="Enable PII redaction")
    mig.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    mig.add_argument("--confidence", "-c",
                     choices=["high", "medium", "low", "all"], default="medium")
    mig.add_argument("--dry-run", action="store_true", help="Preview without writing")
    mig.add_argument("--verbose", "-v", action="store_true")
    mig.add_argument("--stats", action="store_true", help="Show category stats")
    mig.add_argument("--schema", choices=["v4", "v5"], default="v4",
                     help="Output schema version (default: v4)")

    # -- extract ------------------------------------------------------------
    ext = sub.add_parser("extract", help="Extract context from export file")
    ext.add_argument("input_file", help="Path to chat export file")
    ext.add_argument("--output", "-o", help="Output JSON path")
    ext.add_argument("--format", "-f",
                     choices=["auto", "openai", "gemini", "perplexity",
                              "jsonl", "api_logs", "messages", "text", "generic"],
                     default="auto")
    ext.add_argument("--merge", "-m", help="Existing context file to merge with")
    ext.add_argument("--redact", action="store_true")
    ext.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    ext.add_argument("--verbose", "-v", action="store_true")
    ext.add_argument("--stats", action="store_true")

    # -- import -------------------------------------------------------------
    imp = sub.add_parser("import", help="Import context to platform formats")
    imp.add_argument("input_file", help="Path to context JSON file")
    imp.add_argument("--to", "-t", dest="to", default="all",
                     choices=list(PLATFORM_FORMATS.keys()),
                     help="Target platform shortcut (default: all)")
    imp.add_argument("--output", "-o", default="./output", help="Output directory")
    imp.add_argument("--confidence", "-c",
                     choices=["high", "medium", "low", "all"], default="medium")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--verbose", "-v", action="store_true")

    # -- query (Phase 1) ---------------------------------------------------
    qry = sub.add_parser("query", help="Query a context/graph file")
    qry.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    qry.add_argument("--node", help="Look up a node by label")
    qry.add_argument("--neighbors", help="Get neighbors of a node by label")

    # -- stats (Phase 1) ---------------------------------------------------
    st = sub.add_parser("stats", help="Show graph/context statistics")
    st.add_argument("input_file", help="Path to context JSON (v4 or v5)")

    return parser


# ---------------------------------------------------------------------------
# Subcommand runners
# ---------------------------------------------------------------------------

def run_extract(args):
    """Extract context from an export file and save as JSON."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    print(f"Loading: {input_path}")
    try:
        data, detected_format = load_file(input_path)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    fmt = args.format if args.format != "auto" else detected_format
    print(f"Format: {fmt}")

    # PII redactor
    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                print(f"Redaction patterns file not found: {pp}")
                return 1
            with open(pp, "r", encoding="utf-8") as f:
                custom_patterns = json.load(f)
        redactor = PIIRedactor(custom_patterns)
        print("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    # Merge
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            print(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            print(f"Merge file not found: {merge_path} (proceeding without merge)")

    result = _run_extraction(extractor, data, fmt)

    stats = extractor.context.stats()
    print(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to: {output_path}")
    return 0


def run_import(args):
    """Import a context JSON file and export to platform formats."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    print(f"Loading: {input_path}")
    ctx = NormalizedContext.load(input_path)
    min_conf = CONFIDENCE_THRESHOLDS[args.confidence]
    format_keys = PLATFORM_FORMATS[args.to]
    output_dir = Path(args.output)

    if args.dry_run:
        print("\nDRY RUN PREVIEW")
        for key in format_keys:
            export_fn, filename, is_json = EXPORT_DISPATCH[key]
            result = export_fn(ctx, min_conf)
            print(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                print(line)
        return 0

    outputs = _write_exports(ctx, min_conf, format_keys, output_dir, args.verbose)

    print(f"\nExported {len(outputs)} files to {output_dir}/:")
    for key, path in outputs:
        print(f"   {key}: {path.name}")
    return 0


def run_migrate(args):
    """Full pipeline: extract from export file, then import to platform formats."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    # --- Extract phase ---
    print(f"Loading: {input_path}")
    try:
        data, detected_format = load_file(input_path)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    fmt = args.input_format if args.input_format != "auto" else detected_format
    print(f"Format: {fmt}")

    # PII redactor
    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            pp = Path(args.redact_patterns)
            if not pp.exists():
                print(f"Redaction patterns file not found: {pp}")
                return 1
            with open(pp, "r", encoding="utf-8") as f:
                custom_patterns = json.load(f)
        redactor = PIIRedactor(custom_patterns)
        print("PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    # Merge
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            print(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            print(f"Merge file not found: {merge_path} (proceeding without merge)")

    v4_data = _run_extraction(extractor, data, fmt)

    stats = extractor.context.stats()
    print(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

    # --- Save intermediate context.json ---
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.schema == "v5":
        graph = upgrade_v4_to_v5(v4_data)
        v5_data = graph.export_v5()
        ctx_path = output_dir / "context.json"
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(v5_data, f, indent=2)
        if args.verbose:
            gs = graph.stats()
            print(f"   v5 graph: {gs['node_count']} nodes, {gs['edge_count']} edges")
            print(f"   saved v5 context: {ctx_path}")
    else:
        ctx_path = output_dir / "context.json"
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(v4_data, f, indent=2)
        if args.verbose:
            print(f"   saved intermediate context: {ctx_path}")

    # --- Import phase (in-memory handoff) ---
    ctx = NormalizedContext.from_v4(v4_data)
    min_conf = CONFIDENCE_THRESHOLDS[args.confidence]
    format_keys = PLATFORM_FORMATS[args.to]

    if args.dry_run:
        print("\nDRY RUN PREVIEW")
        for key in format_keys:
            export_fn, filename, is_json = EXPORT_DISPATCH[key]
            result = export_fn(ctx, min_conf)
            print(f"\n--- {key} ({filename}) ---")
            text = json.dumps(result, indent=2) if is_json else result
            for line in text.split("\n")[:30]:
                print(line)
        return 0

    outputs = _write_exports(ctx, min_conf, format_keys, output_dir, args.verbose)

    print(f"\nExported {len(outputs) + 1} files to {output_dir}/:")
    print(f"   context: context.json")
    for key, path in outputs:
        print(f"   {key}: {path.name}")
    return 0


def run_query(args):
    """Query nodes/neighbors in a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Load or convert to graph
    version = data.get("schema_version", "")
    if version.startswith("5"):
        graph = CortexGraph.from_v5_json(data)
    else:
        graph = upgrade_v4_to_v5(data)

    if args.node:
        nodes = graph.find_nodes(label=args.node)
        if not nodes:
            print(f"No node found with label '{args.node}'")
            return 0
        for node in nodes:
            print(f"Node: {node.label} (id={node.id})")
            print(f"  Tags: {', '.join(node.tags)}")
            print(f"  Confidence: {node.confidence:.2f}")
            print(f"  Mentions: {node.mention_count}")
            if node.brief:
                print(f"  Brief: {node.brief}")
            if node.full_description:
                print(f"  Description: {node.full_description}")
        return 0

    if args.neighbors:
        nodes = graph.find_nodes(label=args.neighbors)
        if not nodes:
            print(f"No node found with label '{args.neighbors}'")
            return 0
        node = nodes[0]
        neighbors = graph.get_neighbors(node.id)
        if not neighbors:
            print(f"No neighbors for '{node.label}'")
            return 0
        print(f"Neighbors of '{node.label}':")
        for edge, neighbor in neighbors:
            print(f"  --[{edge.relation}]--> {neighbor.label} (conf={neighbor.confidence:.2f})")
        return 0

    print("Specify --node <label> or --neighbors <label>")
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
    if st["tag_distribution"]:
        print("Tag distribution:")
        for tag, count in sorted(st["tag_distribution"].items(), key=lambda x: -x[1]):
            print(f"  {tag}: {count}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # Default-subcommand routing: if the first arg is not a known subcommand,
    # treat it as a file path and route to the "migrate" subcommand.
    known_subcommands = ("extract", "import", "migrate", "query", "stats", "-h", "--help")
    if argv and argv[0] not in known_subcommands:
        argv = ["migrate"] + list(argv)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand is None:
        parser.print_help()
        return 1

    if args.subcommand == "extract":
        return run_extract(args)
    elif args.subcommand == "import":
        return run_import(args)
    elif args.subcommand == "query":
        return run_query(args)
    elif args.subcommand == "stats":
        return run_stats(args)
    else:
        return run_migrate(args)


if __name__ == "__main__":
    sys.exit(main())
