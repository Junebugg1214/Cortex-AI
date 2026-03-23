#!/usr/bin/env python3
"""
Cortex CLI — unified migration tool: extract + import in a single command.

Usage:
    cortex chatgpt-export.zip --to claude
    cortex extract chatgpt-export.zip -o context.json
    cortex import context.json --to notion -o ./output
"""

import argparse
import json
import sys
from pathlib import Path

from cortex.adapters import ADAPTERS
from cortex.claims import (
    ClaimEvent,
    ClaimLedger,
    claim_event_to_node,
    extraction_source_label,
    record_graph_claims,
    stamp_graph_provenance,
)
from cortex.compat import upgrade_v4_to_v5
from cortex.connectors import connector_to_text
from cortex.contradictions import ContradictionEngine
from cortex.extract_memory import (
    AggressiveExtractor,
    PIIRedactor,
    build_eval_compat_view,
    load_file,
    merge_contexts,
)
from cortex.graph import CortexGraph, Node
from cortex.import_memory import (
    CONFIDENCE_THRESHOLDS,
    NormalizedContext,
    export_claude_memories,
    export_claude_preferences,
    export_full_json,
    export_google_docs,
    export_notion,
    export_notion_database_json,
    export_summary,
    export_system_prompt,
)
from cortex.memory_ops import (
    blame_memory_nodes,
    forget_nodes,
    list_memory_conflicts,
    retract_source,
    resolve_memory_conflict,
    set_memory_node,
    show_memory_nodes,
)
from cortex.merge import clear_merge_state, load_merge_state, load_merge_worktree, merge_refs, resolve_merge_conflict, save_merge_state
from cortex.review import parse_failure_policies, review_graphs
from cortex.temporal import drift_score
from cortex.timeline import TimelineGenerator
from cortex.upai.disclosure import BUILTIN_POLICIES
from cortex.upai.identity import UPAIIdentity
from cortex.upai.versioning import VersionStore

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
    "claude-preferences": (export_claude_preferences, "claude_preferences.txt", False),
    "claude-memories": (export_claude_memories, "claude_memories.json", True),
    "system-prompt": (export_system_prompt, "system_prompt.txt", False),
    "notion": (export_notion, "notion_page.md", False),
    "notion-db": (export_notion_database_json, "notion_database.json", True),
    "gdocs": (export_google_docs, "google_docs.html", False),
    "summary": (export_summary, "summary.md", False),
    "full": (export_full_json, "full_export.json", True),
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
) -> tuple[dict, int]:
    graph = upgrade_v4_to_v5(v4_output)
    source = extraction_source_label(input_path)
    claim_count = 0

    if record_claims:
        stamp_graph_provenance(
            graph,
            source=source,
            method="extract",
            metadata={"input_format": fmt, "input_file": str(input_path)},
        )
        if store_dir is not None:
            ledger = ClaimLedger(store_dir)
            events = record_graph_claims(
                graph,
                ledger,
                op="assert",
                source=source,
                method="extract",
                metadata={"input_format": fmt, "input_file": str(input_path)},
            )
            claim_count = len(events)

    result = graph.export_v4()
    if "conflicts" in v4_output:
        result["conflicts"] = list(v4_output.get("conflicts", []))
    if "redaction_summary" in v4_output:
        result["redaction_summary"] = v4_output["redaction_summary"]
    result.update(build_eval_compat_view(result))
    return result, claim_count


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cortex",
        description="Cortex — local AI identity and memory CLI.",
    )
    sub = parser.add_subparsers(dest="subcommand")

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
        choices=["auto", "openai", "gemini", "perplexity", "jsonl", "api_logs", "messages", "text", "generic"],
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
    mig.add_argument("--schema", choices=["v4", "v5"], default="v4", help="Output schema version (default: v4)")
    mig.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    mig.add_argument("--no-claims", action="store_true", help="Skip provenance stamping and claim-ledger recording")
    mig.add_argument(
        "--discover-edges", action="store_true", help="Run smart edge extraction (pattern + co-occurrence)"
    )
    mig.add_argument("--llm", action="store_true", help="LLM-assisted edge extraction (future, stub)")

    # -- extract ------------------------------------------------------------
    ext = sub.add_parser("extract", help="Extract context from export file")
    ext.add_argument("input_file", help="Path to chat export file")
    ext.add_argument("--output", "-o", help="Output JSON path")
    ext.add_argument(
        "--format",
        "-f",
        choices=["auto", "openai", "gemini", "perplexity", "jsonl", "api_logs", "messages", "text", "generic"],
        default="auto",
    )
    ext.add_argument("--merge", "-m", help="Existing context file to merge with")
    ext.add_argument("--redact", action="store_true")
    ext.add_argument("--redact-patterns", help="Custom redaction patterns JSON file")
    ext.add_argument("--verbose", "-v", action="store_true")
    ext.add_argument("--stats", action="store_true")
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

    # -- claim (ledger) ----------------------------------------------------
    clm = sub.add_parser("claim", help="Inspect the local claim ledger")
    clm_sub = clm.add_subparsers(dest="claim_subcommand")

    clm_log = clm_sub.add_parser("log", help="List recent claim events")
    clm_log.add_argument("--store-dir", default=".cortex", help="Claim ledger directory (default: .cortex)")
    clm_log.add_argument("--label", help="Filter by label or alias")
    clm_log.add_argument("--node-id", help="Filter by node id")
    clm_log.add_argument("--source", help="Filter by source")
    clm_log.add_argument("--version", help="Filter by version id prefix")
    clm_log.add_argument("--op", choices=["assert", "retract", "accept", "reject", "supersede"], help="Filter by operation")
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

    # -- branch (Git-for-AI-Memory) ---------------------------------------
    br = sub.add_parser("branch", help="List or create memory branches")
    br.add_argument("branch_name", nargs="?", help="Branch name to create")
    br.add_argument("--from", dest="from_ref", default="HEAD", help="Start point ref (default: HEAD)")
    br.add_argument("--switch", action="store_true", help="Switch to the new branch after creating it")
    br.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    br.add_argument("--format", choices=["json", "text"], default="text")

    # -- switch (Git-for-AI-Memory) ---------------------------------------
    sw = sub.add_parser("switch", help="Switch the active memory branch")
    sw.add_argument("branch_name", help="Branch name to switch to")
    sw.add_argument("-c", "--create", action="store_true", help="Create the branch if it does not exist")
    sw.add_argument("--from", dest="from_ref", default="HEAD", help="Start point when creating a branch (default: HEAD)")
    sw.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")

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

    # -- sync (Phase 3) ----------------------------------------------------
    sy = sub.add_parser("sync", help="Disclosure-filtered export via platform adapters")
    sy.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    sy.add_argument("--to", "-t", required=True, choices=list(ADAPTERS.keys()), help="Target platform adapter")
    sy.add_argument(
        "--policy",
        "-p",
        default="full",
        choices=list(BUILTIN_POLICIES.keys()),
        help="Disclosure policy (default: full)",
    )
    sy.add_argument("--output", "-o", default="./output", help="Output directory")
    sy.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")

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
        help="Target platforms: claude-code, claude-code-project, cursor, "
        "copilot, windsurf, gemini-cli, or 'all' (default: claude-code)",
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
    claim_count = 0
    if not args.no_claims:
        result, claim_count = _finalize_extraction_output(
            result,
            input_path=input_path,
            fmt=fmt,
            store_dir=Path(args.store_dir),
            record_claims=True,
        )

    stats = extractor.context.stats()
    print(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to: {output_path}")
    if not args.no_claims:
        print(f"Recorded {claim_count} claim event(s) to {Path(args.store_dir) / 'claims.jsonl'}")
    return 0


def run_ingest(args):
    """Normalize connector input and extract it into Cortex memory."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    print(f"Loading connector input: {input_path}")
    try:
        normalized_text = connector_to_text(args.kind, input_path)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    if args.preview:
        print(normalized_text, end="" if normalized_text.endswith("\n") else "\n")
        return 0

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

    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            print(f"Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            print(f"Merge file not found: {merge_path} (proceeding without merge)")

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
    print(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to: {output_path}")
    if not args.no_claims:
        print(f"Recorded {claim_count} claim event(s) to {Path(args.store_dir) / 'claims.jsonl'}")
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
    print(f"Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    if args.stats or args.verbose:
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

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
    print("   context: context.json")
    for key, path in outputs:
        print(f"   {key}: {path.name}")
    if not args.no_claims and not args.dry_run:
        print(f"   claims: {claim_count} event(s) -> {Path(args.store_dir) / 'claims.jsonl'}")
    return 0


def run_query(args):
    """Query nodes/neighbors in a context file."""
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = _load_graph(input_path)
    if args.at:
        graph = graph.graph_at(args.at)

    # --- Phase 1 queries (--node, --neighbors) ---
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
            if getattr(node, "status", ""):
                print(f"  Status: {node.status}")
            if getattr(node, "valid_from", "") or getattr(node, "valid_to", ""):
                print(f"  Valid: {getattr(node, 'valid_from', '') or '?'} -> {getattr(node, 'valid_to', '') or '?'}")
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
        if not nodes:
            print(f"No nodes with tag '{args.category}'")
            return 0
        print(f"Nodes tagged '{args.category}' ({len(nodes)}):")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.path:
        from_label, to_label = args.path
        paths = engine.query_path(from_label, to_label)
        if not paths:
            print(f"No path from '{from_label}' to '{to_label}'")
            return 0
        print(f"Path from '{from_label}' to '{to_label}':")
        for node in paths[0]:
            print(f"  -> {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.changed_since:
        result = engine.query_changed(args.changed_since)
        print(f"Changes since {result['since']}: {result['total_changed']} total")
        if result["new_nodes"]:
            print(f"\nNew ({len(result['new_nodes'])}):")
            for n in result["new_nodes"]:
                print(f"  + {n['label']} (conf={n['confidence']:.2f})")
        if result["updated_nodes"]:
            print(f"\nUpdated ({len(result['updated_nodes'])}):")
            for n in result["updated_nodes"]:
                print(f"  ~ {n['label']} (conf={n['confidence']:.2f})")
        return 0

    if args.strongest:
        nodes = engine.query_strongest(args.strongest)
        print(f"Top {len(nodes)} by confidence:")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.weakest:
        nodes = engine.query_weakest(args.weakest)
        print(f"Bottom {len(nodes)} by confidence:")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.isolated:
        analyzer = GapAnalyzer()
        isolated = analyzer.isolated_nodes(graph)
        if not isolated:
            print("No isolated nodes.")
            return 0
        print(f"Isolated nodes ({len(isolated)}):")
        for node in isolated:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.related is not None:
        if not args.related:
            print("Specify a label: --related <LABEL>")
            return 1
        nodes = engine.query_related(args.related, depth=args.related_depth)
        if not nodes:
            print(f"No related nodes for '{args.related}'")
            return 0
        print(f"Related to '{args.related}' (depth={args.related_depth}):")
        for node in nodes:
            print(f"  {node.label} (conf={node.confidence:.2f})")
        return 0

    if args.components:
        comps = connected_components(graph)
        if not comps:
            print("No components (empty graph).")
            return 0
        print(f"Connected components ({len(comps)}):")
        for i, comp in enumerate(comps, 1):
            labels = sorted(graph.get_node(nid).label for nid in comp if graph.get_node(nid))
            print(f"  {i}. [{len(comp)} nodes] {', '.join(labels[:10])}{'...' if len(labels) > 10 else ''}")
        return 0

    if args.search:
        results = graph.semantic_search(args.search, limit=args.limit)
        if not results:
            print(f"No search results for '{args.search}'")
            return 0
        print(f"Search results for '{args.search}' ({len(results)}):")
        for item in results:
            node = item["node"]
            aliases = f" | aliases: {', '.join(node.aliases)}" if getattr(node, "aliases", []) else ""
            print(f"  {node.label} (score={item['score']:.4f}, conf={node.confidence:.2f}){aliases}")
        return 0

    if args.dsl:
        result = execute_query(graph, args.dsl)
        if result.get("type") == "search" and args.limit and len(result.get("results", [])) > args.limit:
            result["results"] = result["results"][: args.limit]
            result["count"] = len(result["results"])
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.nl:
        result = parse_nl_query(args.nl, engine)
        print(json.dumps(result, indent=2, default=str))
        return 0

    print(
        "Specify a query flag: --node, --neighbors, --category, --path, "
        "--changed-since, --strongest, --weakest, --isolated, --related, "
        "--components, --search, --dsl, --nl, --at"
    )
    return 1


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


def _load_identity(store_dir: Path) -> UPAIIdentity | None:
    id_path = store_dir / "identity.json"
    if id_path.exists():
        return UPAIIdentity.load(store_dir)
    return None


def _maybe_commit_graph(graph: CortexGraph, store_dir: Path, message: str | None) -> str | None:
    if not message:
        return None
    store = VersionStore(store_dir)
    identity = _load_identity(store_dir)
    version = store.commit(graph, message, source="manual", identity=identity)
    return version.version_id


def _emit_result(result, output_format: str) -> int:
    if output_format == "json":
        print(json.dumps(result, indent=2))
        return 0
    return -1


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


def run_memory_conflicts(args):
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
        ClaimLedger(Path(args.store_dir)).append(event)
        result["claim_id"] = event.claim_id
        result["claim_event_id"] = event.event_id
    if _emit_result(result, args.format) == 0:
        return 0
    print(f"{'Created' if result['created'] else 'Updated'} node {result['node_id']}.")
    return 0


def run_memory_retract(args):
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
        ledger = ClaimLedger(Path(args.store_dir))
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
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)

    store_path = Path(args.store_dir)
    store = VersionStore(store_path) if (store_path / "history.json").exists() else None
    ledger = ClaimLedger(store_path) if (store_path / "claims.jsonl").exists() else None
    result = blame_memory_nodes(
        graph,
        label=args.label,
        node_id=args.node_id,
        store=store,
        ledger=ledger,
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
            print(f"  Lifecycle: {node.get('status') or 'unspecified'} | {node.get('valid_from') or '?'} -> {node.get('valid_to') or '?'}")
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
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1
    graph = _load_graph(input_path)

    store_path = Path(args.store_dir)
    store = VersionStore(store_path) if (store_path / "history.json").exists() else None
    ledger = ClaimLedger(store_path) if (store_path / "claims.jsonl").exists() else None
    result = blame_memory_nodes(
        graph,
        label=args.label,
        node_id=args.node_id,
        store=store,
        ledger=ledger,
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
                print(
                    f"    {entry['timestamp']} {entry['version_id'][:8]} "
                    f"[{entry['source']}] {entry['message']}"
                )
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


def _find_claim_target_node(graph: CortexGraph, event: ClaimEvent) -> Node | None:
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


def _load_claim_or_error(store_dir: Path, claim_id: str) -> tuple[ClaimLedger, ClaimEvent | None]:
    ledger = ClaimLedger(store_dir)
    return ledger, ledger.latest_event(claim_id)


def run_claim_accept(args):
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
    ledger = ClaimLedger(Path(args.store_dir))
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
    ledger = ClaimLedger(Path(args.store_dir))
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


def _resolve_version_or_exit(store: VersionStore, version_ref: str) -> str:
    resolved = store.resolve_ref(version_ref)
    if resolved is None:
        print(f"Version not found or ambiguous: {version_ref}")
        raise SystemExit(1)
    return resolved


def run_diff(args):
    """Compare two stored graph versions."""
    store = VersionStore(Path(args.store_dir))
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
    return 0


def run_checkout(args):
    """Write a stored graph version to a file."""
    store = VersionStore(Path(args.store_dir))
    version_id = _resolve_version_or_exit(store, args.version_id)
    graph = store.checkout(version_id, verify=not args.no_verify)
    output_path = Path(args.output) if args.output else Path(f"{version_id}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")
    print(f"Checked out {version_id} to {output_path}")
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
    print(f"  Branch: {version.branch}")
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
    store = VersionStore(Path(args.store_dir))

    if args.branch_name:
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
        print(json.dumps({"current_branch": store.current_branch(), "branches": branches}, indent=2))
        return 0

    for branch in branches:
        marker = "*" if branch["current"] else " "
        head = branch["head"][:8] if branch["head"] else "(empty)"
        print(f"{marker} {branch['name']:<24} {head}")
    return 0


def run_switch(args):
    """Switch the active memory branch."""
    store = VersionStore(Path(args.store_dir))
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
    store_dir = Path(args.store_dir)
    store = VersionStore(store_dir)
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
        state = load_merge_state(store_dir)
        if state is None:
            print("No pending merge state found.")
            return 1
        conflicts = state.get("conflicts", [])
        if conflicts:
            print(f"Cannot commit merge; {len(conflicts)} conflict(s) remain.")
            return 1
        graph = load_merge_worktree(store_dir)
        identity = UPAIIdentity.load(store_dir) if (store_dir / "identity.json").exists() else None
        message = args.message or f"Merge branch '{state['other_ref']}' into {state['current_branch']}"
        merge_parent_ids = [state["other_version"]] if state.get("other_version") and state.get("other_version") != state.get("current_version") else []
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
        identity = UPAIIdentity.load(store_dir) if (store_dir / "identity.json").exists() else None
        message = args.message or f"Merge branch '{args.ref_name}' into {current_branch}"
        merge_parent_ids = [result.other_version] if result.other_version and result.other_version != result.current_version else []
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
            print("  Pending merge state saved. Use `cortex merge --conflicts` and `cortex merge --resolve <id> --choose ...`.")
        return 1
    if payload.get("commit_id"):
        print(f"  Committed merge: {payload['commit_id']}")
    elif args.dry_run:
        print("  Dry run only, no commit created.")
    return 0


def run_review(args):
    """Review a graph or stored ref against a baseline."""
    store = VersionStore(Path(args.store_dir))
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
    return 0 if not should_fail else 1


def run_log(args):
    """Show version history."""
    store_dir = Path(args.store_dir)
    store = VersionStore(store_dir)
    ref = None if args.all else (args.branch or "HEAD")
    versions = store.log(limit=args.limit, ref=ref)

    if not versions:
        print("No version history found.")
        return 0

    current_head = store.resolve_ref("HEAD")
    for v in versions:
        marker = "*" if v.version_id == current_head else " "
        print(f"{marker} {v.version_id}  {v.timestamp}  [{v.source}] ({v.branch})")
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
            print(
                f"  - {g['label']}: {g['kind']}"
                + (f" [{g['status']}]" if g.get("status") else "")
            )

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
        generate_compact_context,
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
        context = generate_compact_context(config)
        if context:
            print("Context that would be injected:\n")
            print(context)
            print(f"\n({len(context)} chars)")
        else:
            print("No context generated (graph may be empty or missing).")
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
    from cortex.hooks import HookConfig, _load_graph, generate_compact_context

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
    context = generate_compact_context(config)
    if context:
        print(context)
    else:
        print("No context generated (graph may be empty).", file=sys.stderr)
    return 0


def run_context_write(args):
    """Write identity context to AI coding tool config files."""
    from cortex.context import CONTEXT_TARGETS, watch_and_refresh, write_context

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    # Validate platform names
    platforms = args.platforms
    if "all" not in platforms:
        for p in platforms:
            if p not in CONTEXT_TARGETS:
                print(f"Unknown platform: {p}")
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
    if argv is None:
        argv = sys.argv[1:]

    # Default-subcommand routing: if the first arg is not a known subcommand,
    # treat it as a file path and route to the "migrate" subcommand.
    known_subcommands = (
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
        "identity",
        "commit",
        "branch",
        "switch",
        "merge",
        "review",
        "log",
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
        "rotate",
        "pull",
        "completion",
        "-h",
        "--help",
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
    elif args.subcommand == "completion":
        return run_completion(args)
    else:
        return run_migrate(args)


if __name__ == "__main__":
    sys.exit(main())
