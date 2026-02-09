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

# Cortex graph imports (Phase 1 + Phase 2)
sys.path.insert(0, str(_ROOT))
from cortex.graph import CortexGraph
from cortex.compat import upgrade_v4_to_v5, downgrade_v5_to_v4
from cortex.temporal import drift_score
from cortex.contradictions import ContradictionEngine
from cortex.timeline import TimelineGenerator
from cortex.upai.identity import UPAIIdentity
from cortex.upai.disclosure import BUILTIN_POLICIES
from cortex.upai.versioning import VersionStore
from cortex.adapters import ADAPTERS

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

    # -- timeline (Phase 2) ------------------------------------------------
    tl = sub.add_parser("timeline", help="Generate timeline from context/graph")
    tl.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    tl.add_argument("--from", dest="from_date", help="Start date (ISO-8601)")
    tl.add_argument("--to", dest="to_date", help="End date (ISO-8601)")
    tl.add_argument("--format", "-f", dest="output_format",
                    choices=["md", "html"], default="md",
                    help="Output format (default: md)")

    # -- contradictions (Phase 2) ------------------------------------------
    ct = sub.add_parser("contradictions", help="Detect contradictions in context/graph")
    ct.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    ct.add_argument("--severity", type=float, default=0.0,
                    help="Minimum severity threshold (0.0-1.0)")
    ct.add_argument("--type", dest="contradiction_type",
                    choices=["negation_conflict", "temporal_flip",
                             "source_conflict", "tag_conflict"],
                    help="Filter by contradiction type")

    # -- drift (Phase 2) ---------------------------------------------------
    dr = sub.add_parser("drift", help="Compute identity drift between two graphs")
    dr.add_argument("input_file", help="Path to first context JSON (v4 or v5)")
    dr.add_argument("--compare", required=True,
                    help="Path to second context JSON to compare against")

    # -- identity (Phase 3) ------------------------------------------------
    ident = sub.add_parser("identity", help="Init/show UPAI identity")
    ident.add_argument("--init", action="store_true", help="Generate new identity")
    ident.add_argument("--name", help="Human-readable name for identity")
    ident.add_argument("--show", action="store_true", help="Show current identity")
    ident.add_argument("--store-dir", default=".cortex",
                       help="Identity store directory (default: .cortex)")

    # -- commit (Phase 3) --------------------------------------------------
    cm = sub.add_parser("commit", help="Version a graph snapshot")
    cm.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    cm.add_argument("-m", "--message", required=True, help="Commit message")
    cm.add_argument("--source", default="manual",
                    help="Source label (extraction, merge, manual)")
    cm.add_argument("--store-dir", default=".cortex",
                    help="Version store directory (default: .cortex)")

    # -- log (Phase 3) -----------------------------------------------------
    lg = sub.add_parser("log", help="Show version history")
    lg.add_argument("--limit", type=int, default=10, help="Max entries to show")
    lg.add_argument("--store-dir", default=".cortex",
                    help="Version store directory (default: .cortex)")

    # -- sync (Phase 3) ----------------------------------------------------
    sy = sub.add_parser("sync", help="Disclosure-filtered export via platform adapters")
    sy.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    sy.add_argument("--to", "-t", required=True,
                    choices=list(ADAPTERS.keys()),
                    help="Target platform adapter")
    sy.add_argument("--policy", "-p", default="full",
                    choices=list(BUILTIN_POLICIES.keys()),
                    help="Disclosure policy (default: full)")
    sy.add_argument("--output", "-o", default="./output",
                    help="Output directory")
    sy.add_argument("--store-dir", default=".cortex",
                    help="Identity store directory (default: .cortex)")

    # -- verify (Phase 3) --------------------------------------------------
    vr = sub.add_parser("verify", help="Verify a signed export")
    vr.add_argument("input_file", help="Path to signed export file")

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


def _load_graph(input_path: Path) -> CortexGraph:
    """Load a v4 or v5 JSON file and return a CortexGraph."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    version = data.get("schema_version", "")
    if version.startswith("5"):
        return CortexGraph.from_v5_json(data)
    return upgrade_v4_to_v5(data)


def run_timeline(args):
    """Generate a timeline from a context/graph file."""
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


def run_identity(args):
    """Init or show UPAI identity."""
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

    print("Specify --init or --show")
    return 1


def run_commit(args):
    """Version a graph snapshot."""
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

    store = VersionStore(store_dir)
    version = store.commit(graph, args.message, source=args.source, identity=identity)

    print(f"Committed: {version.version_id}")
    print(f"  Message: {version.message}")
    print(f"  Source: {version.source}")
    print(f"  Nodes: {version.node_count}, Edges: {version.edge_count}")
    if version.parent_id:
        print(f"  Parent: {version.parent_id}")
    if version.signature:
        print(f"  Signed: yes")
    return 0


def run_log(args):
    """Show version history."""
    store_dir = Path(args.store_dir)
    store = VersionStore(store_dir)
    versions = store.log(limit=args.limit)

    if not versions:
        print("No version history found.")
        return 0

    for v in versions:
        print(f"  {v.version_id}  {v.timestamp}  [{v.source}]")
        print(f"    {v.message}")
        print(f"    nodes={v.node_count} edges={v.edge_count}", end="")
        if v.signature:
            print("  signed", end="")
        print()
    return 0


def run_sync(args):
    """Disclosure-filtered export via platform adapters."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    adapter = ADAPTERS[args.to]
    policy = BUILTIN_POLICIES[args.policy]
    output_dir = Path(args.output)

    # Load identity if available
    identity = None
    store_dir = Path(args.store_dir)
    id_path = store_dir / "identity.json"
    if id_path.exists():
        identity = UPAIIdentity.load(store_dir)

    paths = adapter.push(graph, policy, identity=identity, output_dir=output_dir)

    print(f"Synced to {args.to} with policy '{args.policy}':")
    for p in paths:
        print(f"  {p}")
    return 0


def run_verify(args):
    """Verify a signed export file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    data = json.loads(input_path.read_text())

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
    known_subcommands = (
        "extract", "import", "migrate", "query", "stats",
        "timeline", "contradictions", "drift",
        "identity", "commit", "log", "sync", "verify",
        "-h", "--help",
    )
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
    elif args.subcommand == "timeline":
        return run_timeline(args)
    elif args.subcommand == "contradictions":
        return run_contradictions(args)
    elif args.subcommand == "drift":
        return run_drift(args)
    elif args.subcommand == "identity":
        return run_identity(args)
    elif args.subcommand == "commit":
        return run_commit(args)
    elif args.subcommand == "log":
        return run_log(args)
    elif args.subcommand == "sync":
        return run_sync(args)
    elif args.subcommand == "verify":
        return run_verify(args)
    else:
        return run_migrate(args)


if __name__ == "__main__":
    sys.exit(main())
