"""Graph and store integrity checks for Cortex."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cortex.graph import CortexGraph


class IntegrityCheckError(ValueError):
    """Raised when Cortex integrity checking cannot complete safely."""


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    """A single integrity issue discovered during validation."""

    code: str
    message: str
    severity: str

    def to_dict(self) -> dict[str, str]:
        """Serialize the issue."""
        return {"code": self.code, "message": self.message, "severity": self.severity}


def graph_checksum(graph: CortexGraph) -> str:
    """Compute a deterministic checksum for a graph payload."""
    exported = graph.export_v5()
    meta = dict(exported.get("meta", {}))
    meta.pop("generated_at", None)
    exported["meta"] = meta
    graph_payload = dict(exported.get("graph", {}))
    graph_payload["nodes"] = {
        node_id: graph_payload.get("nodes", {}).get(node_id) for node_id in sorted(graph_payload.get("nodes", {}))
    }
    graph_payload["edges"] = {
        edge_id: graph_payload.get("edges", {}).get(edge_id) for edge_id in sorted(graph_payload.get("edges", {}))
    }
    exported["graph"] = graph_payload
    payload = json.dumps(exported, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_graph_integrity(graph: CortexGraph) -> dict[str, Any]:
    """Validate graph lineage, edge references, and retraction consistency."""
    issues: list[IntegrityIssue] = []
    orphaned_nodes = [
        {"id": node.id, "label": node.label} for node in graph.nodes.values() if not list(node.provenance)
    ]
    if orphaned_nodes:
        issues.append(
            IntegrityIssue(
                code="orphaned_nodes",
                message=f"{len(orphaned_nodes)} node(s) have no source lineage.",
                severity="warning",
            )
        )
    broken_edges = [
        {"id": edge.id, "source_id": edge.source_id, "target_id": edge.target_id}
        for edge in graph.edges.values()
        if edge.source_id not in graph.nodes or edge.target_id not in graph.nodes
    ]
    if broken_edges:
        issues.append(
            IntegrityIssue(
                code="broken_edges",
                message=f"{len(broken_edges)} edge(s) reference missing nodes.",
                severity="error",
            )
        )
    retracted_sources = {
        str(item.get("source", "")).strip()
        for item in list(graph.meta.get("retractions", []) or [])
        if str(item.get("source", "")).strip()
    }
    nodes_with_retracted_sources = [
        {"id": node.id, "label": node.label}
        for node in graph.nodes.values()
        if any(
            str(item.get("source_id") or item.get("source") or "").strip() in retracted_sources
            for item in node.provenance
        )
    ]
    if nodes_with_retracted_sources:
        issues.append(
            IntegrityIssue(
                code="retracted_lineage_present",
                message=f"{len(nodes_with_retracted_sources)} node(s) still reference retracted sources.",
                severity="error",
            )
        )
    status = "ok"
    if any(issue.severity == "error" for issue in issues):
        status = "error"
    elif issues:
        status = "warning"
    return {
        "status": status,
        "checksum": graph_checksum(graph),
        "orphaned_nodes": orphaned_nodes,
        "broken_edges": broken_edges,
        "nodes_with_retracted_sources": nodes_with_retracted_sources,
        "issues": [issue.to_dict() for issue in issues],
    }


def check_store_integrity(store_dir: str | Path) -> dict[str, Any]:
    """Validate the current store head and version ancestry."""
    from cortex.storage import get_storage_backend

    backend = get_storage_backend(Path(store_dir))
    current_branch = backend.versions.current_branch()
    head = backend.versions.resolve_ref("HEAD")
    graph_issues = {"status": "ok", "checksum": "", "issues": []}
    if head is not None:
        try:
            graph_issues = check_graph_integrity(backend.versions.checkout(head))
        except Exception as exc:  # noqa: BLE001 - integrity checks should report all store corruption
            graph_issues = {
                "status": "error",
                "checksum": "",
                "issues": [
                    IntegrityIssue(
                        code="head_snapshot_integrity_failed",
                        message=str(exc),
                        severity="error",
                    ).to_dict()
                ],
            }

    history = backend.versions.log(limit=10_000)
    known_version_ids = {item.version_id for item in history}
    broken_version_chain = [
        item.version_id for item in history if item.parent_id and item.parent_id not in known_version_ids
    ]
    snapshot_integrity_issues: list[dict[str, str]] = []
    for item in history:
        try:
            backend.versions.checkout(item.version_id)
        except Exception as exc:  # noqa: BLE001 - surface all corrupt snapshots instead of aborting early
            snapshot_integrity_issues.append(
                {
                    "version_id": item.version_id,
                    "message": str(exc),
                    "severity": "error",
                }
            )

    chain_integrity = {"status": "ok", "legacy_unchained": False, "chain_issues": []}
    verify_chain = getattr(backend.versions, "verify_chain_integrity", None)
    if callable(verify_chain):
        chain_integrity = verify_chain()

    status = graph_issues["status"]
    if broken_version_chain or snapshot_integrity_issues or chain_integrity.get("status") == "error":
        status = "error"
    elif status == "ok" and chain_integrity.get("status") == "warning":
        status = "warning"
    return {
        "status": status,
        "store_dir": str(Path(store_dir).resolve()),
        "current_branch": current_branch,
        "head": head,
        "graph_integrity": graph_issues,
        "broken_version_chain": broken_version_chain,
        "snapshot_integrity_issues": snapshot_integrity_issues,
        "chain_integrity": chain_integrity,
    }


__all__ = ["IntegrityCheckError", "IntegrityIssue", "check_graph_integrity", "check_store_integrity", "graph_checksum"]
