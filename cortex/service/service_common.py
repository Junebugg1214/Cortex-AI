from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.compat import upgrade_v4_to_v5
from cortex.graph import CortexGraph
from cortex.upai.identity import UPAIIdentity


def _coerce_graph(payload: dict[str, Any]) -> CortexGraph:
    version = str(payload.get("schema_version", ""))
    if version.startswith("5") or version.startswith("6"):
        return CortexGraph.from_v5_json(payload)
    return upgrade_v4_to_v5(payload)


def _load_identity(store_dir: Path) -> UPAIIdentity | None:
    identity_path = store_dir / "identity.json"
    if not identity_path.exists():
        return None
    return UPAIIdentity.load(store_dir)


def _node_payload(node: Any) -> dict[str, Any]:
    if hasattr(node, "to_dict"):
        return node.to_dict()
    return dict(node)


def _merge_payload(
    *,
    current_ref: str,
    current_branch: str,
    other_ref: str,
    result: Any,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "current_ref": current_ref,
        "current_branch": current_branch,
        "merged_ref": other_ref,
        "base_version": result.base_version,
        "current_version": result.current_version,
        "other_version": result.other_version,
        "summary": result.summary,
        "conflicts": [conflict.to_dict() for conflict in result.conflicts],
        "graph": result.merged.export_v5(),
        "ok": result.ok,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "_coerce_graph",
    "_load_identity",
    "_merge_payload",
    "_node_payload",
    "_now_iso",
]
