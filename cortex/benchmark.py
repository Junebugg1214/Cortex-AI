from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Callable

from cortex.graph import CortexGraph, Edge, Node
from cortex.release import build_release_metadata
from cortex.service import MemoryService
from cortex.storage import build_sqlite_backend


def _build_graph(*, prefix: str, node_count: int) -> CortexGraph:
    graph = CortexGraph()
    previous_id: str | None = None
    for index in range(node_count):
        node_id = f"{prefix.lower().replace(' ', '-')}-n{index}"
        label = f"{prefix} Node {index}"
        graph.add_node(
            Node(
                id=node_id,
                label=label,
                aliases=[label.lower()],
                tags=["benchmark", "release" if index % 2 == 0 else "self_hosted"],
                confidence=0.8 + ((index % 10) * 0.01),
                brief=f"Benchmark payload for {label}",
            )
        )
        if previous_id is not None:
            graph.add_edge(
                Edge(
                    id=f"{prefix.lower().replace(' ', '-')}-e{index}",
                    source_id=previous_id,
                    target_id=node_id,
                    relation="related_to",
                    confidence=0.7,
                )
            )
        previous_id = node_id
    return graph


def _measure(operation: Callable[[], Any]) -> tuple[float, Any]:
    started = perf_counter()
    result = operation()
    return (perf_counter() - started) * 1000.0, result


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summary(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {"count": 0, "min_ms": 0.0, "mean_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "count": len(samples),
        "min_ms": round(min(samples), 3),
        "mean_ms": round(mean(samples), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
    }


def run_release_benchmark(
    *,
    store_dir: str | Path,
    iterations: int = 3,
    node_count: int = 24,
) -> dict[str, Any]:
    resolved_store_dir = Path(store_dir)
    backend = build_sqlite_backend(resolved_store_dir)
    service = MemoryService(store_dir=resolved_store_dir, backend=backend)

    commit_samples: list[float] = []
    query_samples: list[float] = []
    merge_samples: list[float] = []
    index_samples: list[float] = []
    last_results: dict[str, Any] = {}

    for iteration in range(iterations):
        baseline_graph = _build_graph(prefix=f"Main {iteration}", node_count=node_count)
        commit_ms, commit_result = _measure(
            lambda graph=baseline_graph, iteration=iteration: service.commit(
                graph=graph.export_v5(),
                message=f"benchmark baseline {iteration}",
                source="benchmark",
                actor="benchmark",
            )
        )
        commit_samples.append(commit_ms)

        branch_name = f"bench/feature-{iteration}"
        service.create_branch(name=branch_name, from_ref="HEAD", switch=False, actor="benchmark")
        service.switch_branch(name=branch_name, actor="benchmark")
        feature_graph = CortexGraph()
        for node in baseline_graph.nodes.values():
            feature_graph.add_node(node)
        extra_graph = _build_graph(prefix=f"Feature {iteration}", node_count=4)
        for node in extra_graph.nodes.values():
            feature_graph.add_node(node)
        for edge in extra_graph.edges.values():
            feature_graph.add_edge(edge)
        feature_graph.add_edge(
            Edge(
                id=f"feature-link-{iteration}",
                source_id=f"main-{iteration}-n0",
                target_id=f"feature-{iteration}-n0",
                relation="extends",
                confidence=0.8,
            )
        )
        service.commit(
            graph=feature_graph.export_v5(),
            message=f"benchmark feature {iteration}",
            source="benchmark",
            actor="benchmark",
        )
        service.switch_branch(name="main", actor="benchmark")

        query_ms, query_result = _measure(
            lambda branch_name=branch_name, iteration=iteration: service.query_search(
                query=f"Feature {iteration} Node",
                ref=branch_name,
                limit=5,
            )
        )
        query_samples.append(query_ms)

        merge_ms, merge_result = _measure(
            lambda branch_name=branch_name: service.merge_preview(
                other_ref=branch_name,
                current_ref="main",
                persist=False,
            )
        )
        merge_samples.append(merge_ms)

        index_ms, index_result = _measure(lambda branch_name=branch_name: service.index_rebuild(ref=branch_name))
        index_samples.append(index_ms)

        last_results = {
            "commit": commit_result,
            "query": {"count": query_result["count"], "search_backend": query_result["search_backend"]},
            "merge": {"ok": merge_result["ok"], "conflicts": len(merge_result["conflicts"])},
            "index": {
                "last_indexed_commit": index_result.get("last_indexed_commit"),
                "indexed_refs": index_result.get("indexed_refs", []),
            },
        }

    release = build_release_metadata(service.openapi())
    return {
        "status": "ok",
        "release": release,
        "store_dir": str(resolved_store_dir.resolve()),
        "iterations": iterations,
        "node_count": node_count,
        "operations": {
            "commit": _summary(commit_samples),
            "query_search": _summary(query_samples),
            "merge_preview": _summary(merge_samples),
            "index_rebuild": _summary(index_samples),
        },
        "last_results": last_results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cortex-bench",
        description="Run a lightweight self-host benchmark across commit, query, merge preview, and index rebuild.",
    )
    parser.add_argument(
        "--store-dir", default=".cortex-bench", help="Benchmark store directory (default: .cortex-bench)"
    )
    parser.add_argument("--iterations", type=int, default=3, help="Number of benchmark iterations (default: 3)")
    parser.add_argument("--nodes", type=int, default=24, help="Nodes per generated graph (default: 24)")
    parser.add_argument("--output", "-o", help="Optional JSON output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_release_benchmark(store_dir=args.store_dir, iterations=args.iterations, node_count=args.nodes)
    payload = json.dumps(result, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
        print(f"Wrote benchmark report to {output_path}")
    print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
