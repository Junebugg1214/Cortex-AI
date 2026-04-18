#!/usr/bin/env python3
"""Versioning, merge, governance, and remote graph command handlers for the Cortex CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from cortex import cli_parser as cli_parser_module

if TYPE_CHECKING:
    from cortex.graph import CortexGraph
    from cortex.schemas.memory_v1 import GovernanceRuleRecord


@dataclass(frozen=True)
class GraphVersionCliContext:
    """Callbacks supplied by the graph CLI facade."""

    emit_result: Callable[[Any, str], int]
    current_branch_or_ref: Callable[[Any, str | None], str]
    governance_decision_or_error: Callable[..., object | None]
    load_graph: Callable[[Path], "CortexGraph"]
    load_identity: Callable[[Path], object | None]
    maybe_commit_graph: Callable[["CortexGraph", Path, str | None], str | None]
    save_graph: Callable[["CortexGraph", Path], None]


GOVERNANCE_ACTION_CHOICES = cli_parser_module.GOVERNANCE_ACTION_CHOICES


def _store_dir_hint(store_dir: Path | str) -> str:
    value = str(store_dir)
    return "" if value == ".cortex" else f" --store-dir {value}"


def _print_next_steps(*steps: str) -> None:
    if not steps:
        return
    print("  Next:")
    for step in steps:
        print(f"    {step}")


def _resolve_version_or_exit(store, version_ref: str) -> str:
    resolved = store.resolve_ref(version_ref)
    if resolved is None:
        print(f"Version not found or ambiguous: {version_ref}")
        raise SystemExit(1)
    return resolved


def _resolve_version_at_or_exit(store, timestamp: str, ref: str | None = None) -> str:
    resolved = store.resolve_at(timestamp, ref=ref)
    if resolved is None:
        scope = f" on {ref}" if ref else ""
        print(f"Version not found at or before {timestamp}{scope}")
        raise SystemExit(1)
    return resolved


def run_diff(args, *, ctx: GraphVersionCliContext):
    """Compare two stored graph versions."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    if (
        ctx.governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=ctx.current_branch_or_ref(store, args.version_a),
        )
        is None
    ):
        return 1
    if (
        ctx.governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=ctx.current_branch_or_ref(store, args.version_b),
        )
        is None
    ):
        return 1
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
    print(f"  Semantic changes: {diff.get('semantic_summary', {}).get('total', 0)}")
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
    if diff.get("semantic_changes"):
        print("\nSemantic changes:")
        for item in diff["semantic_changes"][:20]:
            print(f"  * {item['type']}: {item['description']}")
    return 0


def run_integrity(args, *, ctx: GraphVersionCliContext):
    """Check store lineage, version history, and graph consistency."""
    from cortex.integrity import check_store_integrity

    if args.integrity_subcommand == "rehash":
        from cortex.upai.versioning import VersionStore

        if not args.confirm:
            print("Refusing to rehash version history without --confirm.")
            print(f"  Inspect first: cortex integrity check{_store_dir_hint(args.store_dir)}")
            return 1
        store = VersionStore(Path(args.store_dir))
        try:
            payload = store.rehash_chain_v2(confirm=True)
        except Exception as exc:  # noqa: BLE001 - CLI should report migration failures clearly
            print(f"Rehash failed: {exc}")
            return 1
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        print("Integrity rehash: OK")
        print(f"  Migrated versions: {payload.get('migrated', 0)}")
        print(f"  Migration log: {payload.get('log_path')}")
        _print_next_steps(f"cortex integrity check{_store_dir_hint(args.store_dir)}")
        return 0

    payload = check_store_integrity(Path(args.store_dir))
    exit_code = 1 if payload.get("status") == "error" else 0
    if ctx.emit_result(payload, args.format) == 0:
        return exit_code

    graph_integrity = payload.get("graph_integrity", {})
    print(f"Integrity check: {payload.get('status', 'error').upper()}")
    print(f"  Store: {payload.get('store_dir', args.store_dir)}")
    print(f"  Current branch: {payload.get('current_branch') or '(none)'}")
    print(f"  Head: {payload.get('head') or '(none)'}")
    if graph_integrity.get("checksum"):
        print(f"  Graph checksum: {graph_integrity['checksum']}")
    broken_chain = payload.get("broken_version_chain", [])
    if broken_chain:
        print(f"  Broken version chain entries: {len(broken_chain)}")
        for version_id in broken_chain[:20]:
            print(f"    - {version_id}")
    snapshot_issues = payload.get("snapshot_integrity_issues", [])
    if snapshot_issues:
        print(f"  Snapshot integrity issues: {len(snapshot_issues)}")
        for issue in snapshot_issues[:20]:
            print(f"    - {issue.get('version_id')}: {issue.get('message', '')}")
    chain_integrity = payload.get("chain_integrity", {})
    legacy_unchained = bool(chain_integrity.get("legacy_unchained"))
    if legacy_unchained:
        print("  Chain hash: legacy unchained")
        print(f"    Legacy versions: {len(chain_integrity.get('legacy_versions', []))}")
        print(f"    Migrate: cortex integrity rehash --confirm{_store_dir_hint(args.store_dir)}")
    chain_issues = list(chain_integrity.get("chain_issues", []))
    if chain_issues:
        print(f"  Chain hash issues: {len(chain_issues)}")
        for issue in chain_issues[:20]:
            print(
                f"    - {issue.get('version_id')}: expected {issue.get('expected_version_id')} "
                f"({issue.get('message', '')})"
            )
    issues = list(graph_integrity.get("issues", []))
    if not issues and not broken_chain and not snapshot_issues and not chain_issues and not legacy_unchained:
        print("  No integrity issues detected.")
        return exit_code
    if issues:
        print("  Issues:")
        for issue in issues:
            severity = str(issue.get("severity", "warning")).upper()
            print(f"    - {severity} {issue.get('code', 'unknown')}: {issue.get('message', '')}")
    return exit_code


def run_checkout(args, *, ctx: GraphVersionCliContext):
    """Write a stored graph version to a file."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    if (
        ctx.governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=ctx.current_branch_or_ref(store, args.version_id),
        )
        is None
    ):
        return 1
    version_id = _resolve_version_or_exit(store, args.version_id)
    graph = store.checkout(version_id, verify=not args.no_verify)
    output_path = Path(args.output) if args.output else Path(f"{version_id}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")
    print(f"Checked out {version_id} to {output_path}")
    return 0


def run_rollback(args, *, ctx: GraphVersionCliContext):
    """Restore a stored graph state as a new commit without rewriting history."""
    from cortex.storage import get_storage_backend

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    current_branch = store.current_branch()

    if args.target_ref:
        target_version = _resolve_version_or_exit(store, args.target_ref)
        target_label = args.target_ref
    else:
        target_version = _resolve_version_at_or_exit(store, args.target_time, ref=args.ref)
        target_label = args.target_time

    restored = store.checkout(target_version)
    baseline_version = store.resolve_ref("HEAD")
    baseline_graph = store.checkout(baseline_version) if baseline_version else None
    if (
        ctx.governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="rollback",
            namespace=current_branch,
            current_graph=restored,
            baseline_graph=baseline_graph,
            approve=args.approve,
        )
        is None
    ):
        return 1

    ctx.save_graph(restored, input_path)
    identity = ctx.load_identity(store_dir)
    message = args.message or f"Rollback {current_branch} to {target_label}"
    version = store.commit(restored, message, source="rollback", identity=identity)
    payload = {
        "status": "ok",
        "target": target_label,
        "target_version": target_version,
        "rollback_commit": version.version_id,
        "branch": version.namespace,
        "output": str(input_path),
    }
    if ctx.emit_result(payload, args.format) == 0:
        return 0
    print(f"Rolled back {current_branch} to {target_version} as new commit {version.version_id}.")
    print(f"  Wrote restored graph to {input_path}")
    return 0


def run_identity(args, *, ctx: GraphVersionCliContext):
    """Init or show UPAI identity."""
    from cortex.upai.identity import UPAIIdentity

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
        keychain = Keychain(store_dir)
        history = keychain.get_history()
        if not history:
            print("No key history found.")
            return 0
        errors = keychain.verify_rotation_chain()
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


def run_commit(args, *, ctx: GraphVersionCliContext):
    """Version a graph snapshot."""
    from cortex.storage import get_storage_backend
    from cortex.upai.identity import UPAIIdentity

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    graph = ctx.load_graph(input_path)
    store_dir = Path(args.store_dir)

    identity = None
    id_path = store_dir / "identity.json"
    if id_path.exists():
        identity = UPAIIdentity.load(store_dir)

    store = get_storage_backend(store_dir).versions
    baseline_version = store.resolve_ref("HEAD")
    baseline_graph = store.checkout(baseline_version) if baseline_version else None
    if (
        ctx.governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="write",
            namespace=store.current_branch(),
            current_graph=graph,
            baseline_graph=baseline_graph,
            approve=args.approve,
        )
        is None
    ):
        return 1
    version = store.commit(graph, args.message, source=args.source, identity=identity)

    print(f"Committed: {version.version_id}")
    print(f"  Branch: {version.namespace}")
    print(f"  Message: {version.message}")
    print(f"  Source: {version.source}")
    print(f"  Nodes: {version.node_count}, Edges: {version.edge_count}")
    if version.parent_id:
        print(f"  Parent: {version.parent_id}")
    if version.signature:
        print("  Signed: yes")
    return 0


def run_branch(args, *, ctx: GraphVersionCliContext):
    """List or create memory branches."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions

    if args.branch_name:
        if (
            ctx.governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="branch",
                namespace=args.branch_name,
            )
            is None
        ):
            return 1
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
        print(
            json.dumps(
                {"current_branch": store.current_branch(), "branches": [branch.to_dict() for branch in branches]},
                indent=2,
            )
        )
        return 0

    for branch in branches:
        marker = "*" if branch.current else " "
        head = branch.head[:8] if branch.head else "(empty)"
        print(f"{marker} {branch.name:<24} {head}")
    return 0


def run_switch(args, *, ctx: GraphVersionCliContext):
    """Switch the active memory branch or run a platform portability migration."""
    if getattr(args, "to_platform", None):
        from cortex.portable_runtime import default_output_dir, switch_portability

        input_path = Path(args.from_ref)
        if not input_path.exists():
            print(f"File not found: {input_path}")
            return 1
        project_dir = Path(args.project) if args.project else Path.cwd()
        output_dir = Path(args.output) if args.output else default_output_dir(Path(args.store_dir))
        payload = switch_portability(
            input_path,
            to_target=args.to_platform,
            store_dir=Path(args.store_dir),
            project_dir=project_dir,
            output_dir=output_dir,
            input_format=args.input_format,
            policy_name=args.policy,
            max_chars=args.max_chars,
            dry_run=args.dry_run,
        )
        print(f"Portable switch ready: {payload['source']} -> {args.to_platform}")
        for result in payload["targets"]:
            joined = ", ".join(result["paths"]) if result["paths"] else "(no files)"
            print(f"  {result['target']}: {joined} [{result['status']}]")
        return 0

    if not args.branch_name:
        print("Specify a branch name, or use --to for platform switch mode.")
        return 1
    from cortex.storage import get_storage_backend

    store = get_storage_backend(Path(args.store_dir)).versions
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


def run_merge(args, *, ctx: GraphVersionCliContext):
    """Merge another branch/ref into the current branch."""
    from cortex.merge import (
        clear_merge_state,
        load_merge_state,
        load_merge_worktree,
        merge_refs,
        resolve_merge_conflict,
        save_merge_state,
    )
    from cortex.review import merge_preview as review_merge_preview
    from cortex.storage import get_storage_backend
    from cortex.upai.identity import UPAIIdentity

    store_dir = Path(args.store_dir)
    store = get_storage_backend(store_dir).versions
    current_branch = store.current_branch()

    if args.ref_name in {"preview", "commit"}:
        if not args.base or not args.incoming:
            print("`cortex merge preview|commit` requires --base <branch> and --incoming <branch>.")
            _print_next_steps(
                f"Preview first: cortex merge preview --base main --incoming feature-branch{_store_dir_hint(store_dir)}",
                f"Commit after a clean preview: cortex merge commit --base main --incoming feature-branch{_store_dir_hint(store_dir)}",
            )
            return 1
        try:
            result = merge_refs(store, args.base, args.incoming)
        except ValueError as exc:
            print(str(exc))
            return 1
        payload = {
            "status": "ok",
            "base": args.base,
            "incoming": args.incoming,
            **review_merge_preview(result),
        }
        if args.ref_name == "preview":
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return 0 if not payload["direct_conflicts"] else 1
            print(f"Merge preview {args.incoming} -> {args.base}")
            print(
                "  Classes:"
                f" DIRECT={payload['summary'].get('conflict_classes', {}).get('DIRECT', 0)}"
                f" ALIAS={payload['summary'].get('conflict_classes', {}).get('ALIAS', 0)}"
                f" NOVEL={payload['summary'].get('conflict_classes', {}).get('NOVEL', 0)}"
            )
            for item in payload.get("alias_resolutions", [])[:20]:
                print(f"  alias {item['alias']} -> {item['canonical_label']} ({item['canonical_id']})")
            for conflict in payload.get("direct_conflicts", [])[:20]:
                print(f"  direct {conflict['id']} [{conflict['field']}]: {conflict['description']}")
            if payload["direct_conflicts"]:
                _print_next_steps(
                    f"Inspect the full preview as JSON: cortex merge preview --base {args.base} --incoming {args.incoming}{_store_dir_hint(store_dir)} --format json",
                    f"Commit after DIRECT conflicts are resolved: cortex merge commit --base {args.base} --incoming {args.incoming}{_store_dir_hint(store_dir)}",
                )
            else:
                _print_next_steps(
                    f"Commit this merge: cortex merge commit --base {args.base} --incoming {args.incoming}{_store_dir_hint(store_dir)}",
                )
            return 0 if not payload["direct_conflicts"] else 1

        unresolved_direct = payload["direct_conflicts"]
        if unresolved_direct:
            print(f"Cannot commit merge; {len(unresolved_direct)} unresolved DIRECT conflict(s) remain.")
            _print_next_steps(
                f"Review the conflicts first: cortex merge preview --base {args.base} --incoming {args.incoming}{_store_dir_hint(store_dir)}",
            )
            return 1
        identity = UPAIIdentity.load(store_dir) if (store_dir / "identity.json").exists() else None
        message = args.message or f"Merge branch '{args.incoming}' into {args.base}"
        version = store.commit(
            result.merged,
            message,
            source="merge",
            identity=identity,
            parent_id=result.current_version,
            branch=args.base,
            merge_parent_ids=[result.other_version]
            if result.other_version and result.other_version != result.current_version
            else [],
        )
        payload["commit_id"] = version.version_id
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(f"Committed merge {args.incoming} -> {args.base}: {version.version_id}")
            _print_next_steps(f"Verify the new head: cortex log --branch {args.base}{_store_dir_hint(store_dir)}")
        return 0

    if args.abort:
        state = load_merge_state(store_dir)
        if state is None:
            print("No pending merge state found.")
            return 0
        clear_merge_state(store_dir)
        print(f"Aborted pending merge into {state['current_branch']} from {state['other_ref']}.")
        _print_next_steps(
            f"Start over with a dry run: cortex merge {state['other_ref']}{_store_dir_hint(store_dir)} --dry-run",
        )
        return 0

    if args.conflicts:
        if (
            ctx.governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="read",
                namespace=current_branch,
            )
            is None
        ):
            return 1
        state = load_merge_state(store_dir)
        if state is None:
            payload = {"status": "ok", "pending": False, "conflicts": []}
            if args.format == "json":
                print(json.dumps(payload, indent=2))
            else:
                print("No pending merge conflicts.")
                _print_next_steps("Start a merge first: cortex merge <branch-or-ref>")
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
                conflict_class = str(conflict.get("conflict_class") or "DIRECT")
                print(f"  - {conflict['id']} {conflict_class}/{conflict['kind']}{field}: {conflict['description']}")
            _print_next_steps(
                f"Resolve one conflict: cortex merge --resolve <conflict-id> --choose current{_store_dir_hint(store_dir)}",
                f"Commit after all conflicts are resolved: cortex merge --commit-resolved{_store_dir_hint(store_dir)}",
            )
        return 0

    if args.resolve:
        if not args.choose:
            print("Specify --choose current|incoming when resolving a merge conflict.")
            _print_next_steps(
                f"Keep the current branch value: cortex merge --resolve {args.resolve} --choose current{_store_dir_hint(store_dir)}",
                f"Keep the incoming branch value: cortex merge --resolve {args.resolve} --choose incoming{_store_dir_hint(store_dir)}",
            )
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
            if payload["remaining_conflicts"]:
                _print_next_steps(
                    f"Review remaining conflicts: cortex merge --conflicts{_store_dir_hint(store_dir)}",
                    f"Commit when the list is empty: cortex merge --commit-resolved{_store_dir_hint(store_dir)}",
                )
            else:
                _print_next_steps(
                    f"Commit the resolved merge: cortex merge --commit-resolved{_store_dir_hint(store_dir)}"
                )
        return 0

    if args.commit_resolved:
        baseline_version = store.resolve_ref("HEAD")
        baseline_graph = store.checkout(baseline_version) if baseline_version else None
        state = load_merge_state(store_dir)
        if state is None:
            print("No pending merge state found.")
            _print_next_steps("Start a merge first: cortex merge <branch-or-ref>")
            return 1
        conflicts = state.get("conflicts", [])
        if conflicts:
            print(f"Cannot commit merge; {len(conflicts)} conflict(s) remain.")
            _print_next_steps(
                f"Show the remaining conflicts: cortex merge --conflicts{_store_dir_hint(store_dir)}",
                f"Resolve one conflict: cortex merge --resolve <conflict-id> --choose current{_store_dir_hint(store_dir)}",
            )
            return 1
        graph = load_merge_worktree(store_dir)
        if (
            ctx.governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="merge",
                namespace=current_branch,
                current_graph=graph,
                baseline_graph=baseline_graph,
                approve=args.approve,
            )
            is None
        ):
            return 1
        identity = UPAIIdentity.load(store_dir) if (store_dir / "identity.json").exists() else None
        message = args.message or f"Merge branch '{state['other_ref']}' into {state['current_branch']}"
        merge_parent_ids = (
            [state["other_version"]]
            if state.get("other_version") and state.get("other_version") != state.get("current_version")
            else []
        )
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
            _print_next_steps(
                f"Inspect the merged history: cortex log --branch {current_branch}{_store_dir_hint(store_dir)}"
            )
        return 0

    if not args.ref_name:
        print("Specify a branch/ref to merge, or use --conflicts, --resolve, --commit-resolved, or --abort.")
        _print_next_steps(
            f"Preview a two-branch merge: cortex merge preview --base main --incoming feature-branch{_store_dir_hint(store_dir)}",
            f"Start a merge into the current branch: cortex merge feature-branch{_store_dir_hint(store_dir)} --dry-run",
        )
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
        baseline_version = store.resolve_ref("HEAD")
        baseline_graph = store.checkout(baseline_version) if baseline_version else None
        if (
            ctx.governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="merge",
                namespace=current_branch,
                current_graph=result.merged,
                baseline_graph=baseline_graph,
                approve=args.approve,
            )
            is None
        ):
            return 1
        identity = UPAIIdentity.load(store_dir) if (store_dir / "identity.json").exists() else None
        message = args.message or f"Merge branch '{args.ref_name}' into {current_branch}"
        merge_parent_ids = (
            [result.other_version] if result.other_version and result.other_version != result.current_version else []
        )
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
            print(f"    - {conflict.id} {conflict.conflict_class}/{conflict.kind}{field}: {conflict.description}")
        if not args.dry_run:
            print("  Pending merge state saved.")
            _print_next_steps(
                f"List pending conflicts: cortex merge --conflicts{_store_dir_hint(store_dir)}",
                f"Resolve one conflict: cortex merge --resolve <conflict-id> --choose current{_store_dir_hint(store_dir)}",
                f"Commit after resolving everything: cortex merge --commit-resolved{_store_dir_hint(store_dir)}",
            )
        return 1
    if payload.get("commit_id"):
        print(f"  Committed merge: {payload['commit_id']}")
        _print_next_steps(f"Review the merge result: cortex log --branch {current_branch}{_store_dir_hint(store_dir)}")
    elif args.dry_run:
        print("  Dry run only, no commit created.")
        _print_next_steps(f"Apply the merge when ready: cortex merge {args.ref_name}{_store_dir_hint(store_dir)}")
    return 0


def run_review(args, *, ctx: GraphVersionCliContext):
    """Review a graph or stored ref against a baseline."""
    from cortex.review import parse_failure_policies, pending_candidate_branches, review_graphs
    from cortex.storage import get_storage_backend

    if args.input_file == "pending":
        if not args.mind:
            print("`cortex review pending` requires --mind <id>")
            _print_next_steps(
                f"List pending proposals: cortex review pending --mind <mind-id>{_store_dir_hint(Path(args.store_dir))}"
            )
            return 1
        try:
            payload = pending_candidate_branches(
                Path(args.store_dir),
                args.mind,
                show_conflicts=bool(args.show_conflicts),
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return 0
        print(f"Pending review proposals for Mind `{args.mind}`: {payload['pending_proposal_count']}")
        for item in payload["proposals"]:
            print(
                f"  - {item['proposal_id']} [{item['status']}] "
                f"sources={item['proposed_source_count']} nodes={item['graph_node_count']}"
            )
            if item.get("proposal_path"):
                print(f"      path={item['proposal_path']}")
            if args.show_conflicts:
                for conflict in item.get("resolution_conflicts", [])[:10]:
                    print(
                        f"      conflict={conflict.get('type', 'unknown')} "
                        f"topic={conflict.get('topic', '')} "
                        f"confidence={float(conflict.get('confidence', 0.0)):.2f}"
                    )
        if payload["proposals"]:
            if args.show_conflicts:
                _print_next_steps(
                    "Open one proposal file from the path above and inspect the captured source spans.",
                )
            else:
                _print_next_steps(
                    f"Show low-confidence extraction conflicts: cortex review pending --mind {args.mind} --show-conflicts{_store_dir_hint(Path(args.store_dir))}",
                )
        return 0

    backend = get_storage_backend(Path(args.store_dir))
    store = backend.versions
    if not args.against:
        print("`cortex review` requires --against unless you use `cortex review pending --mind <id>`.")
        _print_next_steps(
            f"Compare against the current head: cortex review --against HEAD{_store_dir_hint(Path(args.store_dir))}",
            f"List pending candidate branches instead: cortex review pending --mind <mind-id>{_store_dir_hint(Path(args.store_dir))}",
        )
        return 1
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
        current_graph = ctx.load_graph(input_path)
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
            f" semantic={summary['semantic_changes']}"
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
        if result["semantic_changes"]:
            print("  Semantic changes:")
            for item in result["semantic_changes"][:10]:
                print(f"    - {item['type']}: {item['description']}")
        if should_fail:
            _print_next_steps(
                f"See a machine-readable report: cortex review --against {args.against}{_store_dir_hint(Path(args.store_dir))} --format json",
                "Fix the flagged contradictions, temporal gaps, or low-confidence changes, then rerun the review.",
            )
        else:
            _print_next_steps("This review passed. You can proceed with your merge or commit.")
    return 0 if not should_fail else 1


def run_log(args, *, ctx: GraphVersionCliContext):
    """Show version history."""
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    backend = get_storage_backend(store_dir)
    store = backend.versions
    ref = None if args.all else (args.branch or "HEAD")
    if (
        ctx.governance_decision_or_error(
            store_dir=store_dir,
            actor=args.actor,
            action="read",
            namespace=ctx.current_branch_or_ref(store, ref),
        )
        is None
    ):
        return 1
    versions = store.log(limit=args.limit, ref=ref)

    if not versions:
        print("No version history found.")
        return 0

    current_head = store.resolve_ref("HEAD")
    for version in versions:
        marker = "*" if version.version_id == current_head else " "
        print(f"{marker} {version.version_id}  {version.timestamp}  [{version.source}] ({version.namespace})")
        print(f"    {version.message}")
        print(f"    nodes={version.node_count} edges={version.edge_count}", end="")
        if version.signature:
            print("  signed", end="")
        print()
    return 0


def _rule_from_args(args, effect: str, tenant_id: str) -> "GovernanceRuleRecord":
    from cortex.schemas.memory_v1 import GovernanceRuleRecord

    invalid_actions = [item for item in args.action if item != "*" and item not in GOVERNANCE_ACTION_CHOICES]
    if invalid_actions:
        raise ValueError(f"Unknown governance action(s): {', '.join(sorted(invalid_actions))}")
    return GovernanceRuleRecord(
        tenant_id=tenant_id,
        name=args.name,
        effect=effect,
        actor_pattern=args.actor_pattern,
        actions=list(args.action),
        namespaces=list(args.namespace),
        require_approval=bool(getattr(args, "require_approval", False)),
        approval_below_confidence=getattr(args, "approval_below_confidence", None),
        approval_tags=list(getattr(args, "approval_tag", [])),
        approval_change_types=list(getattr(args, "approval_change", [])),
        description=getattr(args, "description", ""),
    )


def run_governance(args, *, ctx: GraphVersionCliContext):
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    backend = get_storage_backend(store_dir)
    governance = backend.governance

    if args.governance_subcommand == "list":
        rules = [rule.to_dict() for rule in governance.list_rules()]
        payload = {"rules": rules}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not rules:
            print("No governance rules configured.")
            return 0
        for rule in rules:
            approval = " approval" if rule.get("require_approval") else ""
            print(
                f"{rule['name']}: {rule['effect']} actor={rule['actor_pattern']} "
                f"actions={','.join(rule['actions'])} namespaces={','.join(rule['namespaces'])}{approval}"
            )
        return 0

    if args.governance_subcommand in {"allow", "deny"}:
        try:
            rule = _rule_from_args(args, effect=args.governance_subcommand, tenant_id=backend.tenant_id)
        except ValueError as exc:
            print(str(exc))
            return 1
        governance.upsert_rule(rule)
        payload = {"status": "ok", "rule": rule.to_dict()}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        print(f"Saved governance rule {rule.name}.")
        return 0

    if args.governance_subcommand == "delete":
        removed = governance.remove_rule(args.name)
        payload = {"status": "ok" if removed else "missing", "name": args.name}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if removed:
            print(f"Deleted governance rule {args.name}.")
        else:
            print(f"Governance rule not found: {args.name}")
        return 0 if removed else 1

    if args.governance_subcommand == "check":
        current_graph = None
        baseline_graph = None
        if args.input_file:
            input_path = Path(args.input_file)
            if not input_path.exists():
                print(f"File not found: {input_path}")
                return 1
            current_graph = ctx.load_graph(input_path)
        if args.against:
            store = backend.versions
            baseline_graph = store.checkout(_resolve_version_or_exit(store, args.against))
        decision = governance.authorize(
            args.actor,
            args.action,
            args.namespace,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        )
        if ctx.emit_result(decision.to_dict(), args.format) == 0:
            return 0
        status = "allow" if decision.allowed else "deny"
        print(f"{status.upper()}: actor '{decision.actor}' -> {decision.action} {decision.namespace}")
        if decision.matched_rules:
            print(f"  Rules: {', '.join(decision.matched_rules)}")
        if decision.require_approval:
            print("  Approval required")
        for reason in decision.reasons:
            print(f"  - {reason}")
        return 0 if decision.allowed else 1

    print("Specify a governance subcommand: list, allow, deny, delete, check")
    return 1


def run_remote(args, *, ctx: GraphVersionCliContext):
    from cortex.schemas.memory_v1 import RemoteRecord
    from cortex.storage import get_storage_backend

    store_dir = Path(args.store_dir)
    backend = get_storage_backend(store_dir)
    store = backend.versions

    if args.remote_subcommand == "list":
        remotes = [
            remote.to_dict() | {"store_path": remote.resolved_store_path} for remote in backend.remotes.list_remotes()
        ]
        payload = {"remotes": remotes}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if not remotes:
            print("No remotes configured.")
            return 0
        for remote in remotes:
            allowed = ", ".join(remote.get("allowed_namespaces", []) or [remote["default_branch"]])
            did = str(remote.get("trusted_did") or "")[:24]
            print(
                f"{remote['name']}: {remote['store_path']} (default={remote['default_branch']}, "
                f"allow={allowed}, did={did}...)"
            )
        return 0

    if args.remote_subcommand == "add":
        remote = RemoteRecord(
            tenant_id=backend.tenant_id,
            name=args.name,
            path=args.path,
            default_branch=args.default_branch,
            trusted_did=args.trusted_did,
            trusted_public_key_b64=args.trusted_public_key_b64,
            allowed_namespaces=list(args.allow_namespace or []),
        )
        try:
            backend.remotes.add_remote(remote)
        except ValueError as exc:
            print(str(exc))
            return 1
        stored = next(item for item in backend.remotes.list_remotes() if item.name == args.name)
        payload = {"status": "ok", "remote": stored.to_dict() | {"store_path": stored.resolved_store_path}}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        allowed = ", ".join(stored.allowed_namespaces or [stored.default_branch])
        print(f"Added remote {stored.name} -> {stored.resolved_store_path}")
        print(f"  trusted DID: {stored.trusted_did}")
        print(f"  allowed namespaces: {allowed}")
        return 0

    if args.remote_subcommand == "remove":
        removed = backend.remotes.remove_remote(args.name)
        payload = {"status": "ok" if removed else "missing", "name": args.name}
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        if removed:
            print(f"Removed remote {args.name}.")
        else:
            print(f"Remote not found: {args.name}")
        return 0 if removed else 1

    remotes_by_name = {remote.name: remote for remote in backend.remotes.list_remotes()}
    remote = remotes_by_name.get(args.name)
    if remote is None:
        print(f"Remote not found: {args.name}")
        return 1

    if args.remote_subcommand == "push":
        namespace = ctx.current_branch_or_ref(store, args.branch)
        if (
            ctx.governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="push",
                namespace=namespace,
            )
            is None
        ):
            return 1
        try:
            payload = backend.remotes.push_remote(
                args.name,
                branch=args.branch,
                target_branch=args.to_branch,
                force=args.force,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        print(f"Pushed {payload['branch']} -> {remote.name}:{payload['remote_branch']} ({payload['head']})")
        print(f"  trusted remote: {payload['trusted_remote_did']}")
        print(f"  receipt: {payload['receipt_path']}")
        return 0

    if args.remote_subcommand == "pull":
        remote_branch = args.branch or remote.default_branch
        namespace = args.into_branch or f"remotes/{remote.name}/{remote_branch}"
        if (
            ctx.governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="pull",
                namespace=namespace,
            )
            is None
        ):
            return 1
        try:
            payload = backend.remotes.pull_remote(
                args.name,
                branch=remote_branch,
                into_branch=args.into_branch,
                force=args.force,
                switch=args.switch,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        print(f"Pulled {remote.name}:{remote_branch} -> {payload['branch']} ({payload['head']})")
        print(f"  trusted remote: {payload['trusted_remote_did']}")
        print(f"  receipt: {payload['receipt_path']}")
        return 0

    if args.remote_subcommand == "fork":
        remote_branch = args.remote_branch or remote.default_branch
        if (
            ctx.governance_decision_or_error(
                store_dir=store_dir,
                actor=args.actor,
                action="branch",
                namespace=args.branch_name,
            )
            is None
        ):
            return 1
        try:
            payload = backend.remotes.fork_remote(
                args.name,
                remote_branch=remote_branch,
                local_branch=args.branch_name,
                switch=args.switch,
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        if ctx.emit_result(payload, args.format) == 0:
            return 0
        print(f"Forked {remote.name}:{remote_branch} -> {args.branch_name} ({payload['head']})")
        print(f"  trusted remote: {payload['trusted_remote_did']}")
        print(f"  receipt: {payload['receipt_path']}")
        return 0

    print("Specify a remote subcommand: list, add, remove, push, pull, fork")
    return 1
