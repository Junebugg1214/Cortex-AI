from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cortex.portability.portable_state as _portable_state
import cortex.portability.portable_views as _portable_views
from cortex.atomic_io import atomic_write_text, locked_path
from cortex.graph.graph import CortexGraph
from cortex.hermes_integration import install_hermes_context
from cortex.import_memory import NormalizedContext
from cortex.portability.context import write_context
from cortex.portability.portability import PORTABLE_DIRECT_TARGETS, export_artifact_targets
from cortex.portability.portable_builders import (
    build_git_history_graph,
    build_github_graph,
    build_project_graph,
    build_resume_graph,
)
from cortex.portability.portable_graphs import extract_graph_from_statement, merge_graphs
from cortex.portability.portable_sources import (
    ALL_PORTABLE_TARGETS,
    DEFAULT_DIRECT_TARGETS,
    canonical_target_name,
    display_name,
    expected_tool_paths,
    resolve_requested_targets,
)
from cortex.portability.portable_sources import discover_portability_sources as _discover_portability_sources
from cortex.portability.portable_sources import (
    extract_graph_from_detected_sources as _extract_graph_from_detected_sources,
)
from cortex.portability.portable_sources import graph_from_hermes_paths as _graph_from_hermes_paths
from cortex.portability.portable_sources import search_roots as _search_roots
from cortex.versioning.upai.disclosure import apply_disclosure

if TYPE_CHECKING:
    from cortex.extraction.extract_memory import PIIRedactor

STATE_VERSION = _portable_state.STATE_VERSION
SMART_ROUTE_TAGS = _portable_views.SMART_ROUTE_TAGS
PortabilityState = _portable_state.PortabilityState
TargetState = _portable_state.TargetState


def iso_now() -> str:
    return _portable_state.iso_now()


def portability_dir(store_dir: Path) -> Path:
    return _portable_state.portability_dir(store_dir)


def portability_state_path(store_dir: Path) -> Path:
    return _portable_state.portability_state_path(store_dir)


def portability_snapshot_dir(store_dir: Path) -> Path:
    return _portable_state.portability_snapshot_dir(store_dir)


def default_graph_path(store_dir: Path) -> Path:
    return _portable_state.default_graph_path(store_dir)


def default_output_dir(store_dir: Path) -> Path:
    return _portable_state.default_output_dir(store_dir)


def ensure_state_dirs(store_dir: Path) -> None:
    _portable_state.ensure_state_dirs(store_dir)


def load_portability_state(store_dir: Path) -> PortabilityState:
    return _portable_state.load_portability_state(store_dir)


def save_portability_state(store_dir: Path, state: PortabilityState) -> Path:
    ensure_state_dirs(store_dir)
    path = portability_state_path(store_dir)
    with locked_path(path):
        atomic_write_text(path, json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def file_fingerprint(path: Path) -> str:
    return _portable_state.file_fingerprint(path)


def _graph_fact_rows(graph: CortexGraph) -> list[dict[str, Any]]:
    return _portable_state.graph_fact_rows(graph)


def _write_graph(path: Path, graph: CortexGraph) -> None:
    with locked_path(path):
        atomic_write_text(path, json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def _load_graph(path: Path) -> CortexGraph | None:
    return _portable_state.load_graph(path)


def detect_portability_sources(
    *,
    store_dir: Path,
    project_dir: Path,
    extra_roots: list[Path] | None = None,
) -> list[dict[str, Any]]:
    state = load_portability_state(store_dir)
    output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
    roots = _search_roots(project_dir, extra_roots)
    return _discover_portability_sources(project_dir=project_dir, output_dir=output_dir, roots=roots)


def extract_graph_from_detected_sources(
    *,
    targets: list[str],
    store_dir: Path,
    project_dir: Path,
    extra_roots: list[Path] | None = None,
    include_config_metadata: bool = False,
    include_unmanaged_text: bool = False,
    redactor: PIIRedactor | None = None,
) -> dict[str, Any]:
    detected = detect_portability_sources(store_dir=store_dir, project_dir=project_dir, extra_roots=extra_roots)
    return _extract_graph_from_detected_sources(
        targets=targets,
        store_dir=store_dir,
        detected_sources=detected,
        include_config_metadata=include_config_metadata,
        include_unmanaged_text=include_unmanaged_text,
        redactor=redactor,
    )


def load_canonical_graph(store_dir: Path, state: PortabilityState | None = None) -> tuple[CortexGraph, Path]:
    state = state or load_portability_state(store_dir)
    graph_path = Path(state.graph_path) if state.graph_path else default_graph_path(store_dir)
    graph = _load_graph(graph_path)
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
    _write_graph(target_path, graph)
    state.graph_path = str(target_path)
    state.updated_at = iso_now()
    if not state.output_dir:
        state.output_dir = str(default_output_dir(store_dir))
    save_portability_state(store_dir, state)
    return state, target_path


def _policy_for_target(target: str, *, smart: bool, policy_name: str):
    return _portable_views.policy_for_target(target, smart=smart, policy_name=policy_name)


def _policy_from_target_state(target_state: TargetState):
    return _portable_views.policy_from_target_state(target_state)


def render_portability_context(
    *,
    store_dir: Path,
    target: str,
    project_dir: Path | None = None,
    smart: bool | None = None,
    policy_name: str | None = None,
    max_chars: int = 1500,
) -> dict[str, Any]:
    return _portable_views.render_portability_context(
        store_dir=store_dir,
        target=target,
        project_dir=project_dir,
        smart=smart,
        policy_name=policy_name,
        max_chars=max_chars,
    )


def scan_portability(
    *,
    store_dir: Path,
    project_dir: Path,
    extra_roots: list[Path] | None = None,
    metadata_only: bool = False,
) -> dict[str, Any]:
    return _portable_views.scan_portability(
        store_dir=store_dir,
        project_dir=project_dir,
        extra_roots=extra_roots,
        metadata_only=metadata_only,
    )


def status_portability(*, store_dir: Path, project_dir: Path) -> dict[str, Any]:
    return _portable_views.status_portability(store_dir=store_dir, project_dir=project_dir)


def audit_portability(*, store_dir: Path, project_dir: Path) -> dict[str, Any]:
    return _portable_views.audit_portability(store_dir=store_dir, project_dir=project_dir)


def bar(coverage: float, width: int = 20) -> str:
    return _portable_views.bar(coverage, width=width)


def sync_targets(
    graph: CortexGraph,
    *,
    targets: list[str],
    store_dir: Path,
    project_dir: str | None,
    output_dir: Path,
    graph_path: Path,
    policy_name: str = "technical",
    smart: bool = False,
    max_chars: int = 1500,
    dry_run: bool = False,
    state: PortabilityState | None = None,
    identity: Any | None = None,
    persist_state: bool = True,
) -> dict[str, Any]:
    state = state or load_portability_state(store_dir)
    results: list[dict[str, Any]] = []
    ensure_state_dirs(store_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for target in resolve_requested_targets(targets):
        policy, route_tags = _policy_for_target(target, smart=smart, policy_name=policy_name)
        filtered = apply_disclosure(graph, policy)
        if target == "hermes":
            install_result = install_hermes_context(
                NormalizedContext.from_v5(filtered.export_v5()),
                project_dir=project_dir,
                store_dir=store_dir,
                max_chars=max_chars,
                min_confidence=policy.min_confidence,
                dry_run=dry_run,
            )
            paths = [str(path) for path in install_result.paths]
            status = install_result.status
            note = install_result.note
        elif target in PORTABLE_DIRECT_TARGETS:
            with tempfile.TemporaryDirectory() as tmp_dir:
                filtered_path = Path(tmp_dir) / f"{target}.json"
                _write_graph(filtered_path, filtered)
                write_results = write_context(
                    graph_path=str(filtered_path),
                    platforms=list(PORTABLE_DIRECT_TARGETS[target]),
                    project_dir=project_dir,
                    policy="full",
                    max_chars=max_chars,
                    dry_run=dry_run,
                )
            paths = [str(path) for _, path, status in write_results if status != "skipped" and str(path)]
            status = "ok" if write_results else "skipped"
            note = f"Updated {len(paths)} file(s)"
        else:
            artifact_results = export_artifact_targets(
                filtered,
                NormalizedContext.from_v5(filtered.export_v5()),
                [target],
                output_dir,
                policy_name="full",
                min_confidence=policy.min_confidence,
                identity=identity,
                dry_run=dry_run,
            )
            artifact = artifact_results[0] if artifact_results else None
            paths = [str(path) for path in (artifact.paths if artifact else ())]
            status = artifact.status if artifact else "skipped"
            note = artifact.note if artifact else ""

        snapshot_path = portability_snapshot_dir(store_dir) / f"{target}.json"
        fingerprints = {path: file_fingerprint(Path(path)) for path in paths if Path(path).exists()}
        facts_graph = _graph_from_hermes_paths(paths) if target == "hermes" else filtered
        facts = _graph_fact_rows(facts_graph)
        results.append(
            {
                "target": target,
                "paths": paths,
                "status": status,
                "note": note,
                "fact_count": len(facts),
                "route_tags": route_tags,
                "mode": "smart" if smart else "full",
            }
        )

        if dry_run or not persist_state:
            continue

        _write_graph(snapshot_path, filtered)
        state.targets[target] = TargetState(
            target=target,
            mode="smart" if smart else "full",
            policy=policy_name,
            route_tags=route_tags,
            paths=paths,
            fingerprints=fingerprints,
            fact_ids=[row["id"] for row in facts],
            facts=facts,
            updated_at=iso_now(),
            snapshot_path=str(snapshot_path),
            note=note,
        )

    if not dry_run and persist_state:
        state.graph_path = str(graph_path)
        state.project_dir = project_dir or state.project_dir or str(Path.cwd())
        state.output_dir = str(output_dir)
        state.updated_at = iso_now()
        save_portability_state(store_dir, state)

    return {
        "graph_path": str(graph_path),
        "output_dir": str(output_dir),
        "targets": results,
        "smart": smart,
    }


def remember_and_sync(
    statement: str,
    *,
    store_dir: Path,
    project_dir: Path,
    targets: list[str] | None = None,
    smart: bool = False,
    policy_name: str = "full",
    max_chars: int = 1500,
    dry_run: bool = False,
) -> dict[str, Any]:
    state = load_portability_state(store_dir)
    canonical_graph, graph_path = load_canonical_graph(store_dir, state)
    extracted_graph = extract_graph_from_statement(statement)
    merged = merge_graphs(canonical_graph, extracted_graph)
    if not dry_run:
        state, graph_path = save_canonical_graph(store_dir, merged, state=state, graph_path=graph_path)
    output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
    return {
        "statement": statement,
        "graph_path": str(graph_path),
        "targets": sync_targets(
            merged,
            targets=[canonical_target_name(target) for target in (targets or ALL_PORTABLE_TARGETS)],
            store_dir=store_dir,
            project_dir=str(project_dir),
            output_dir=output_dir,
            graph_path=graph_path,
            policy_name=policy_name,
            smart=smart,
            max_chars=max_chars,
            dry_run=dry_run,
            state=state,
        )["targets"],
        "fact_count": len(merged.nodes),
    }


def build_digital_footprint(
    *,
    sources: list[str],
    inputs: list[str],
    store_dir: Path,
    project_dir: Path,
    search_roots: list[Path] | None = None,
    sync_after: bool = False,
    targets: list[str] | None = None,
    smart: bool = False,
    policy_name: str = "technical",
    max_chars: int = 1500,
) -> dict[str, Any]:
    source_iter = iter(inputs)
    built_graph = CortexGraph()
    summaries: list[dict[str, Any]] = []

    roots = _search_roots(project_dir, search_roots)

    for source in sources:
        if source == "github":
            graph, summary = build_github_graph(roots or [project_dir])
        elif source == "resume":
            try:
                resume_input = Path(next(source_iter))
            except StopIteration as exc:
                raise ValueError("build --from resume requires a file path") from exc
            graph, summary = build_resume_graph(resume_input)
        elif source in {"package.json", "project", "manifest"}:
            graph, summary = build_project_graph(project_dir)
        elif source == "git-history":
            graph, summary = build_git_history_graph(project_dir)
        else:
            raise ValueError(f"Unknown build source: {source}")
        built_graph = merge_graphs(built_graph, graph)
        summaries.append({"source": source, **summary})

    state = load_portability_state(store_dir)
    canonical_graph, graph_path = load_canonical_graph(store_dir, state)
    merged = merge_graphs(canonical_graph, built_graph)
    state, graph_path = save_canonical_graph(store_dir, merged, state=state, graph_path=graph_path)

    payload: dict[str, Any] = {
        "graph_path": str(graph_path),
        "sources": summaries,
        "fact_count": len(merged.nodes),
    }
    if sync_after:
        output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(store_dir)
        sync_targets_list = list(targets or DEFAULT_DIRECT_TARGETS)
        if smart and sync_targets_list == DEFAULT_DIRECT_TARGETS:
            sync_targets_list = list(ALL_PORTABLE_TARGETS)
        payload["targets"] = sync_targets(
            merged,
            targets=[canonical_target_name(target) for target in sync_targets_list],
            store_dir=store_dir,
            project_dir=str(project_dir),
            output_dir=output_dir,
            graph_path=graph_path,
            policy_name=policy_name,
            smart=smart,
            max_chars=max_chars,
            state=state,
        )["targets"]
    return payload


def switch_portability(
    input_path: Path,
    *,
    to_target: str,
    store_dir: Path,
    project_dir: Path,
    output_dir: Path,
    input_format: str = "auto",
    policy_name: str = "technical",
    max_chars: int = 1500,
    dry_run: bool = False,
) -> dict[str, Any]:
    graph = _load_graph(input_path)
    detected_kind = "graph"
    if graph is None:
        from cortex.compat import upgrade_v4_to_v5
        from cortex.extraction.extract_memory import AggressiveExtractor, load_file

        data, detected_format = load_file(input_path)
        extractor = AggressiveExtractor()
        fmt = input_format if input_format != "auto" else detected_format
        payload = _portable_views.run_extraction_data(extractor, data, fmt)
        graph = upgrade_v4_to_v5(payload)
        detected_kind = fmt

    state = load_portability_state(store_dir)
    graph_path = output_dir / "context.json"
    if not dry_run:
        _write_graph(graph_path, graph)

    sync_result = sync_targets(
        graph,
        targets=[canonical_target_name(to_target)],
        store_dir=store_dir,
        project_dir=str(project_dir),
        output_dir=output_dir,
        graph_path=graph_path,
        policy_name=policy_name,
        smart=False,
        max_chars=max_chars,
        dry_run=dry_run,
        state=state,
        persist_state=False,
    )
    return {
        "source": detected_kind,
        "input_path": str(input_path),
        "target": canonical_target_name(to_target),
        "graph_path": str(graph_path),
        "targets": sync_result["targets"],
    }


__all__ = [
    "ALL_PORTABLE_TARGETS",
    "DEFAULT_DIRECT_TARGETS",
    "PortabilityState",
    "STATE_VERSION",
    "SMART_ROUTE_TAGS",
    "TargetState",
    "_policy_for_target",
    "audit_portability",
    "bar",
    "build_digital_footprint",
    "canonical_target_name",
    "default_output_dir",
    "detect_portability_sources",
    "display_name",
    "expected_tool_paths",
    "extract_graph_from_detected_sources",
    "extract_graph_from_statement",
    "load_canonical_graph",
    "load_portability_state",
    "merge_graphs",
    "portability_state_path",
    "remember_and_sync",
    "render_portability_context",
    "save_canonical_graph",
    "save_portability_state",
    "scan_portability",
    "status_portability",
    "switch_portability",
    "sync_targets",
]
