from __future__ import annotations


def add_graph_history_parsers(sub, *, governance_action_choices, builtin_policies):
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

    df = sub.add_parser("diff", help="Compare two stored graph versions")
    df.add_argument("version_a", help="Base version ID, unique prefix, branch name, or HEAD")
    df.add_argument("version_b", help="Target version ID, unique prefix, branch name, or HEAD")
    df.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    df.add_argument("--format", choices=["json", "text"], default="text")
    df.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

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

    ck = sub.add_parser("checkout", help="Write a stored graph version to a file")
    ck.add_argument("version_id", help="Version ID, unique prefix, branch name, or HEAD")
    ck.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    ck.add_argument("--output", "-o", help="Output file path (default: <version>.json)")
    ck.add_argument("--no-verify", action="store_true", help="Skip snapshot integrity verification")
    ck.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

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

    ident = sub.add_parser("identity", help="Init/show UPAI identity")
    ident.add_argument("--init", action="store_true", help="Generate new identity")
    ident.add_argument("--name", help="Human-readable name for identity")
    ident.add_argument("--show", action="store_true", help="Show current identity")
    ident.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    ident.add_argument("--did-doc", action="store_true", help="Output W3C DID document JSON")
    ident.add_argument("--keychain", action="store_true", help="Show key rotation history and status")

    cm = sub.add_parser("commit", help="Version a graph snapshot")
    cm.add_argument("input_file", help="Path to context JSON (v4 or v5)")
    cm.add_argument("-m", "--message", required=True, help="Commit message")
    cm.add_argument("--source", default="manual", help="Source label (extraction, merge, manual)")
    cm.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    cm.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    cm.add_argument("--approve", action="store_true", help="Explicitly approve a gated commit")

    br = sub.add_parser("branch", help="List or create memory branches")
    br.add_argument("branch_name", nargs="?", help="Branch name to create")
    br.add_argument("--from", dest="from_ref", default="HEAD", help="Start point ref (default: HEAD)")
    br.add_argument("--switch", action="store_true", help="Switch to the new branch after creating it")
    br.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    br.add_argument("--format", choices=["json", "text"], default="text")
    br.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

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
        choices=list(builtin_policies.keys()),
        help="Disclosure policy for portable switch mode",
    )
    sw.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    sw.add_argument("--dry-run", action="store_true", help="Preview portable switch without writing files")

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
    mg.add_argument("--base", help="Base branch/ref when using `cortex merge preview|commit`")
    mg.add_argument("--incoming", help="Incoming branch/ref when using `cortex merge preview|commit`")
    mg.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")
    mg.add_argument("--approve", action="store_true", help="Explicitly approve a gated merge")

    rvw = sub.add_parser("review", help="Review a memory graph against a stored ref")
    rvw.add_argument("input_file", nargs="?", help="Optional context JSON to review instead of a stored ref")
    rvw.add_argument("--against", help="Baseline branch/ref/version to compare against")
    rvw.add_argument("--ref", default="HEAD", help="Current branch/ref/version when no input file is provided")
    rvw.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    rvw.add_argument("--mind", help="Mind id when using `cortex review pending`")
    rvw.add_argument(
        "--show-conflicts",
        action="store_true",
        help="Include low-confidence extraction conflicts when using `cortex review pending`",
    )
    rvw.add_argument(
        "--fail-on",
        default="blocking",
        help="Comma-separated review gates: blocking, contradictions, temporal_gaps, low_confidence, retractions, changes, none",
    )
    rvw.add_argument("--format", choices=["json", "text", "md"], default="text")

    lg = sub.add_parser("log", help="Show version history")
    lg.add_argument("--limit", type=int, default=10, help="Max entries to show")
    lg.add_argument("--branch", help="Branch/ref to inspect (default: current branch)")
    lg.add_argument("--all", action="store_true", help="Show global history instead of branch ancestry")
    lg.add_argument("--store-dir", default=".cortex", help="Version store directory (default: .cortex)")
    lg.add_argument("--actor", default="local", help="Actor identity for governance checks (default: local)")

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
        choices=governance_action_choices,
        help="Action to evaluate",
    )
    gov_check.add_argument("--namespace", required=True, help="Namespace or branch name")
    gov_check.add_argument("--input-file", help="Optional current graph to evaluate for approval gating")
    gov_check.add_argument("--against", help="Optional baseline ref for semantic diff/approval gating")
    gov_check.add_argument("--store-dir", default=".cortex", help="Governance store directory (default: .cortex)")
    gov_check.add_argument("--format", choices=["json", "text"], default="text")

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

    sy = sub.add_parser("sync", help="Disclosure-filtered export or smart context propagation")
    sy.add_argument("input_file", nargs="?", help="Path to context JSON (v4 or v5)")
    sy.add_argument("--to", "-t", help="Target platform adapter (legacy mode)")
    sy.add_argument(
        "--policy",
        "-p",
        default="full",
        choices=list(builtin_policies.keys()),
        help="Disclosure policy (default: full)",
    )
    sy.add_argument("--output", "-o", default="./output", help="Output directory")
    sy.add_argument("--store-dir", default=".cortex", help="Identity store directory (default: .cortex)")
    sy.add_argument("--smart", action="store_true", help="Route the right context slice to each supported AI tool")
    sy.add_argument("--project", "-d", help="Project directory for project-scoped targets (default: cwd)")
    sy.add_argument("--max-chars", type=int, default=1500, help="Max characters per written context file")
    sy.add_argument("--format", choices=["json", "text"], default="text")

    vr = sub.add_parser("verify", help="Verify a signed export")
    vr.add_argument("input_file", help="Path to signed export file")
