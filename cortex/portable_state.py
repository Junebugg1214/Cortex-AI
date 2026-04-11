from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.atomic_io import atomic_write_text, locked_path
from cortex.graph import CortexGraph
from cortex.hooks import _load_graph as load_graph_optional

STATE_VERSION = "1.0"


@dataclass(slots=True)
class TargetState:
    target: str
    mode: str = "full"
    policy: str = "technical"
    route_tags: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    fingerprints: dict[str, str] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""
    snapshot_path: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetState:
        return cls(
            target=str(data.get("target", "")),
            mode=str(data.get("mode", "full")),
            policy=str(data.get("policy", "technical")),
            route_tags=[str(tag) for tag in data.get("route_tags", [])],
            paths=[str(path) for path in data.get("paths", [])],
            fingerprints={str(key): str(value) for key, value in data.get("fingerprints", {}).items()},
            fact_ids=[str(value) for value in data.get("fact_ids", [])],
            facts=[dict(item) for item in data.get("facts", [])],
            updated_at=str(data.get("updated_at", "")),
            snapshot_path=str(data.get("snapshot_path", "")),
            note=str(data.get("note", "")),
        )


@dataclass(slots=True)
class PortabilityState:
    graph_path: str = ""
    output_dir: str = ""
    project_dir: str = ""
    updated_at: str = ""
    targets: dict[str, TargetState] = field(default_factory=dict)
    schema_version: str = STATE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_path": self.graph_path,
            "output_dir": self.output_dir,
            "project_dir": self.project_dir,
            "updated_at": self.updated_at,
            "targets": {name: target.to_dict() for name, target in self.targets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortabilityState:
        return cls(
            schema_version=str(data.get("schema_version", STATE_VERSION)),
            graph_path=str(data.get("graph_path", "")),
            output_dir=str(data.get("output_dir", "")),
            project_dir=str(data.get("project_dir", "")),
            updated_at=str(data.get("updated_at", "")),
            targets={
                str(name): TargetState.from_dict(payload)
                for name, payload in dict(data.get("targets", {})).items()
                if isinstance(payload, dict)
            },
        )


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def portability_dir(store_dir: Path) -> Path:
    return store_dir / "portable"


def portability_state_path(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "state.json"


def portability_snapshot_dir(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "snapshots"


def default_graph_path(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "context.json"


def default_output_dir(store_dir: Path) -> Path:
    return portability_dir(store_dir) / "artifacts"


def ensure_state_dirs(store_dir: Path) -> None:
    portability_dir(store_dir).mkdir(parents=True, exist_ok=True)
    portability_snapshot_dir(store_dir).mkdir(parents=True, exist_ok=True)


def load_portability_state(store_dir: Path) -> PortabilityState:
    path = portability_state_path(store_dir)
    if not path.exists():
        return PortabilityState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PortabilityState()
    if not isinstance(data, dict):
        return PortabilityState()
    return PortabilityState.from_dict(data)


def save_portability_state(store_dir: Path, state: PortabilityState) -> Path:
    ensure_state_dirs(store_dir)
    path = portability_state_path(store_dir)
    with locked_path(path):
        atomic_write_text(path, json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_fingerprint(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def graph_fact_rows(graph: CortexGraph) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in sorted(graph.nodes.values(), key=lambda item: (item.label.lower(), item.id)):
        rows.append(
            {
                "id": node.id,
                "label": node.label,
                "brief": node.brief,
                "tags": list(node.tags),
                "confidence": round(node.confidence, 2),
            }
        )
    return rows


def write_graph(path: Path, graph: CortexGraph) -> None:
    with locked_path(path):
        atomic_write_text(path, json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def load_graph(path: Path) -> CortexGraph | None:
    if not path.exists():
        return None
    return load_graph_optional(str(path))


def load_canonical_graph(store_dir: Path, state: PortabilityState | None = None) -> tuple[CortexGraph, Path]:
    state = state or load_portability_state(store_dir)
    graph_path = Path(state.graph_path) if state.graph_path else default_graph_path(store_dir)
    graph = load_graph(graph_path)
    if graph is None:
        graph = CortexGraph()
    return graph, graph_path


def save_canonical_graph(
    store_dir: Path,
    graph: CortexGraph,
    *,
    state: PortabilityState | None = None,
    graph_path: Path | None = None,
) -> tuple[PortabilityState, Path]:
    state = state or load_portability_state(store_dir)
    ensure_state_dirs(store_dir)
    target_path = graph_path or (Path(state.graph_path) if state.graph_path else default_graph_path(store_dir))
    write_graph(target_path, graph)
    state.graph_path = str(target_path)
    state.updated_at = iso_now()
    if not state.output_dir:
        state.output_dir = str(default_output_dir(store_dir))
    save_portability_state(store_dir, state)
    return state, target_path


__all__ = [
    "PortabilityState",
    "STATE_VERSION",
    "TargetState",
    "default_graph_path",
    "default_output_dir",
    "ensure_state_dirs",
    "file_fingerprint",
    "graph_fact_rows",
    "iso_now",
    "load_canonical_graph",
    "load_graph",
    "load_portability_state",
    "portability_dir",
    "portability_snapshot_dir",
    "portability_state_path",
    "save_canonical_graph",
    "save_portability_state",
    "write_graph",
]
