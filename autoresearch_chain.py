#!/usr/bin/env python3
"""
Sequential autoresearch runner for multiple Cortex targets.

Runs the target bundles in order and advances automatically when one target
reaches its score goal or stops after the no-improvement limit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from autoresearch_targets.targets import TARGET_SEQUENCE, get_target

CHAIN_STATUS_JSON = Path("autoresearch_targets/chain_status.json")
CHAIN_STATUS_MD = Path("autoresearch_targets/chain_status.md")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def render_chain_markdown(status: dict[str, Any]) -> str:
    lines = [
        "# Cortex Autoresearch Chain Status",
        "",
        f"- State: {status['state']}",
        f"- Updated: {status['updated_at']}",
        f"- Agent: {status['agent']}",
        f"- Start target: {status['start_at']}",
        f"- Current target: {status['current_target'] or 'none'}",
        f"- Targets completed this run: {len(status['completed_targets'])}",
        "",
        "## Targets",
        "",
        "| Target | State | Best | Goal | Status file |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in status["targets"]:
        best = "-" if item["best_score"] is None else f"{item['best_score']:.4f}"
        goal = f"{item['target_score']:.4f}"
        lines.append(
            f"| {item['key']} | {item['state']} | {best} | {goal} | `{item['status_md']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def write_chain_status(
    *,
    state: str,
    agent: str,
    start_at: str,
    current_target: str | None,
    completed_targets: list[str],
) -> None:
    start_index = next(index for index, target in enumerate(TARGET_SEQUENCE) if target.key == start_at)
    targets_payload = []
    for index, target in enumerate(TARGET_SEQUENCE):
        target_status = load_json(target.status_json_file)
        if index < start_index:
            display_state = "prior"
            best_score = target_status["best_score"] if target_status else None
        elif target.key in completed_targets:
            display_state = "completed"
            best_score = target_status["best_score"] if target_status else None
        elif state == "running" and current_target == target.key:
            display_state = "running"
            best_score = target_status["best_score"] if target_status else None
        else:
            display_state = "pending"
            best_score = None
        targets_payload.append(
            {
                "key": target.key,
                "display_name": target.display_name,
                "state": display_state,
                "best_score": best_score,
                "target_score": target.target_score,
                "status_md": str(target.status_md_file),
            }
        )

    payload = {
        "state": state,
        "updated_at": datetime.utcnow().isoformat(),
        "agent": agent,
        "start_at": start_at,
        "current_target": current_target,
        "completed_targets": list(completed_targets),
        "targets": targets_payload,
    }
    CHAIN_STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    CHAIN_STATUS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    CHAIN_STATUS_MD.write_text(render_chain_markdown(payload), encoding="utf-8")


def ensure_corpus(target_key: str) -> None:
    target = get_target(target_key)
    if target.corpus_manifest.exists():
        return
    print(f"Generating corpus for {target.key}...")
    result = subprocess.run(
        [sys.executable, str(target.generate_corpus_script)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0 or not target.corpus_manifest.exists():
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"Failed to generate corpus for {target.key}: {stderr}")


def run_target(target_key: str, agent: str, agent_timeout: int) -> None:
    target = get_target(target_key)
    ensure_corpus(target_key)
    cmd = [
        sys.executable,
        "-u",
        "autoresearch.py",
        "--agent",
        agent,
        "--agent-timeout",
        str(agent_timeout),
        "--max-experiments",
        str(target.max_experiments),
        "--target",
        f"{target.target_score}",
        "--no-improvement-limit",
        str(target.no_improvement_limit),
        "--target-name",
        target.key,
        "--editable-files",
        ",".join(str(path) for path in target.editable_files),
        "--program-file",
        str(target.program_file),
        "--eval-script",
        str(target.eval_script),
        "--corpus-manifest",
        str(target.corpus_manifest),
        "--log-file",
        str(target.log_file),
        "--status-json-file",
        str(target.status_json_file),
        "--status-md-file",
        str(target.status_md_file),
        "--commit-prefix",
        f"autoresearch {target.key}",
        "--generate-corpus-script",
        str(target.generate_corpus_script),
        "--reset-history",
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Autoresearch failed for target {target.key} with exit code {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Cortex autoresearch targets sequentially")
    parser.add_argument("--agent", choices=["claude", "codex", "manual"], default="manual")
    parser.add_argument("--agent-timeout", type=int, default=1200)
    parser.add_argument(
        "--start-at",
        choices=[target.key for target in TARGET_SEQUENCE],
        default=TARGET_SEQUENCE[0].key,
        help="First target to run in the chain",
    )
    args = parser.parse_args()

    start_index = next(index for index, target in enumerate(TARGET_SEQUENCE) if target.key == args.start_at)
    ordered_targets = TARGET_SEQUENCE[start_index:]
    completed_targets: list[str] = []
    write_chain_status(
        state="running",
        agent=args.agent,
        start_at=args.start_at,
        current_target=ordered_targets[0].key if ordered_targets else None,
        completed_targets=completed_targets,
    )

    for target in ordered_targets:
        print(f"\n=== Running target: {target.key} ===")
        write_chain_status(
            state="running",
            agent=args.agent,
            start_at=args.start_at,
            current_target=target.key,
            completed_targets=completed_targets,
        )
        run_target(target.key, args.agent, args.agent_timeout)
        completed_targets.append(target.key)
        write_chain_status(
            state="running",
            agent=args.agent,
            start_at=args.start_at,
            current_target=target.key,
            completed_targets=completed_targets,
        )

    write_chain_status(
        state="completed",
        agent=args.agent,
        start_at=args.start_at,
        current_target=None,
        completed_targets=completed_targets,
    )
    print("\nAutoresearch chain complete.")


if __name__ == "__main__":
    main()
