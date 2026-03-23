#!/usr/bin/env python3
"""
Cortex autoresearch loop runner.

Runs an eval/commit/revert loop for a single editable file. The default target
remains cortex/extract_memory.py, but the runner can now be pointed at other
target bundles with custom program, eval, corpus, and status files.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_TARGET_NAME = "extract_memory"
DEFAULT_LOG_FILE = Path("autoresearch_log.jsonl")
DEFAULT_STATUS_JSON_FILE = Path("autoresearch_status.json")
DEFAULT_STATUS_MD_FILE = Path("autoresearch_status.md")
DEFAULT_TARGET_SCORE = 0.92
DEFAULT_MAX_EXPERIMENTS = 50
DEFAULT_NO_IMPROVEMENT_LIMIT = 10
DEFAULT_EDITABLE_FILE = Path("cortex/extract_memory.py")
DEFAULT_PROGRAM_FILE = Path("program.md")
DEFAULT_EVAL_SCRIPT = Path("eval.py")
DEFAULT_CORPUS_MANIFEST = Path("corpus/manifest.json")
DEFAULT_AGENT_TIMEOUT = 900
DEFAULT_COMMIT_PREFIX = "autoresearch"


@dataclass(frozen=True)
class RunnerConfig:
    target_name: str
    editable_files: tuple[Path, ...]
    program_file: Path
    eval_script: Path
    corpus_manifest: Path
    log_file: Path
    status_json_file: Path
    status_md_file: Path
    commit_prefix: str


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def format_editable_files(paths: tuple[Path, ...]) -> str:
    if len(paths) == 1:
        return str(paths[0])
    return ", ".join(str(path) for path in paths)


def reset_run_files(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


# Git helpers


def git_commit(editable_files: tuple[Path, ...], message: str) -> bool:
    subprocess.run(["git", "add", *[str(path) for path in editable_files]], capture_output=True)
    result = subprocess.run(["git", "commit", "-m", message], capture_output=True)
    return result.returncode == 0


def git_revert(editable_files: tuple[Path, ...]) -> None:
    subprocess.run(
        ["git", "restore", "--worktree", "--source", "HEAD", *[str(path) for path in editable_files]],
        capture_output=True,
    )


# Score runner


def get_score(eval_script: Path, quiet: bool = True) -> float | None:
    args = [sys.executable, str(eval_script)]
    if quiet:
        args.append("--quiet")
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return float(lines[-1].split()[-1])
    except (ValueError, IndexError):
        return None


# Logging


def log_experiment(log_file: Path, entry: dict[str, Any]) -> None:
    ensure_parent(log_file)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def load_experiments(log_file: Path) -> list[dict[str, Any]]:
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def render_status_markdown(status: dict[str, Any], config: RunnerConfig) -> str:
    lines = [
        f"# Cortex Autoresearch Status ({status['target_name']})",
        "",
        f"- State: {status['state']}",
        f"- Updated: {status['updated_at']}",
        f"- Agent: {status['agent']}",
        f"- Editable files: {', '.join(status['editable_files'])}",
        f"- Program file: {status['program_file']}",
        f"- Eval script: {status['eval_script']}",
        f"- Corpus manifest: {status['corpus_manifest']}",
        f"- Baseline score: {status['baseline_score']:.4f}",
        f"- Best score: {status['best_score']:.4f}",
        f"- Target score: {status['target_score']:.4f}",
        f"- Gap to target: {status['gap_to_target']:.4f}",
        f"- Experiments run: {status['experiments_run']}",
        f"- Improvements kept: {status['improvements_kept']}",
        f"- No-improvement streak: {status['no_improvement_streak']}",
        "",
    ]

    last_experiment = status.get("last_experiment")
    if last_experiment:
        lines.extend(
            [
                "## Latest Experiment",
                "",
                f"- Experiment: {last_experiment['experiment']}",
                f"- Hypothesis: {last_experiment['hypothesis']}",
                f"- Score: {last_experiment['score']}",
                f"- Delta: {last_experiment['delta']}",
                f"- Kept: {last_experiment['kept']}",
                "",
            ]
        )

    recent = status.get("recent_experiments", [])
    if recent:
        lines.extend(
            [
                "## Recent Experiments",
                "",
                "| Exp | Score | Delta | Kept | Hypothesis |",
                "| --- | ---: | ---: | :---: | --- |",
            ]
        )
        for entry in recent:
            score = "FAIL" if entry.get("score") is None else f"{entry['score']:.4f}"
            delta = "-" if entry.get("delta") is None else f"{entry['delta']:+.4f}"
            kept = "yes" if entry.get("kept") else "no"
            hypothesis = str(entry.get("hypothesis", "")).replace("\n", " ").strip()
            lines.append(f"| {entry['experiment']} | {score} | {delta} | {kept} | {hypothesis} |")
        lines.append("")

    lines.extend(
        [
            "## Files",
            "",
            f"- Log: `{config.log_file}`",
            f"- Status JSON: `{config.status_json_file}`",
            f"- Status Markdown: `{config.status_md_file}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_status(
    config: RunnerConfig,
    *,
    state: str,
    agent: str,
    baseline: float,
    best: float,
    target: float,
    no_improvement_streak: int,
    last_experiment: dict[str, Any] | None = None,
) -> None:
    entries = load_experiments(config.log_file)
    kept_entries = [entry for entry in entries if entry.get("kept")]
    status = {
        "target_name": config.target_name,
        "state": state,
        "updated_at": datetime.utcnow().isoformat(),
        "agent": agent,
        "editable_files": [str(path) for path in config.editable_files],
        "program_file": str(config.program_file),
        "eval_script": str(config.eval_script),
        "corpus_manifest": str(config.corpus_manifest),
        "baseline_score": baseline,
        "best_score": best,
        "target_score": target,
        "gap_to_target": max(target - best, 0.0),
        "experiments_run": len(entries),
        "improvements_kept": len(kept_entries),
        "no_improvement_streak": no_improvement_streak,
        "last_experiment": last_experiment,
        "recent_experiments": entries[-10:],
    }
    ensure_parent(config.status_json_file)
    ensure_parent(config.status_md_file)
    config.status_json_file.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    config.status_md_file.write_text(render_status_markdown(status, config), encoding="utf-8")


def print_summary(log_path: Path, target_name: str) -> None:
    if not log_path.exists():
        return
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept_entries = [entry for entry in entries if entry.get("kept")]
    print("\n" + "=" * 55)
    print(f"  Autoresearch complete ({target_name})")
    print(f"  Experiments run:  {len(entries)}")
    print(f"  Improvements kept: {len(kept_entries)}")
    if kept_entries:
        total_gain = sum(entry["delta"] for entry in kept_entries)
        best_entry = max(kept_entries, key=lambda entry: entry["delta"])
        print(f"  Total score gain: +{total_gain:.4f}")
        print(f"  Best experiment:  exp {best_entry['experiment']}")
    print("=" * 55)


# Agent prompt helpers


def recent_history_snippet(log_file: Path, limit: int = 5) -> str:
    entries = load_experiments(log_file)
    if not entries:
        return "No prior experiment history yet."
    lines = []
    for entry in entries[-limit:]:
        score = "FAIL" if entry.get("score") is None else f"{entry['score']:.4f}"
        delta = "n/a" if entry.get("delta") is None else f"{entry['delta']:+.4f}"
        kept = "kept" if entry.get("kept") else "reverted"
        lines.append(
            f"- exp {entry['experiment']:03d}: score={score}, delta={delta}, {kept}, "
            f"hypothesis={entry.get('hypothesis', '')}"
        )
    return "\n".join(lines)


def build_agent_prompt(experiment_num: int, baseline: float, current_best: float, config: RunnerConfig) -> str:
    editable_lines = "\n".join(f"- {path}" for path in config.editable_files)
    return f"""You are running experiment {experiment_num} of the Cortex autoresearch loop.

Current best score: {current_best:.4f}
Baseline score: {baseline:.4f}
Target bundle: {config.target_name}

Read {config.program_file} for full instructions and weak areas.
Editable file set:
{editable_lines}

Recent experiment history:
{recent_history_snippet(config.log_file)}

Your task:
1. Read the editable file set above
2. Form one hypothesis for improvement
3. Apply the change to the editable file set ONLY
4. Do not run the eval script yourself - the loop runner will do it

State your hypothesis clearly before making the change.
Make exactly one change. Do not touch any other file.
At the end of your response, make the first line exactly:
HYPOTHESIS: <short hypothesis>
"""


def extract_hypothesis(agent_output: str, fallback: str) -> str:
    for line in agent_output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("hypothesis:"):
            hypothesis = stripped.split(":", 1)[1].strip()
            if hypothesis:
                return hypothesis
    return fallback


def run_agent(agent: str, prompt: str, experiment_num: int, timeout: int) -> tuple[str, str, str | None]:
    default_hypothesis = f"{agent}_exp_{experiment_num}"

    if agent == "claude":
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        if result.returncode != 0:
            error_text = result.stderr[:400] if result.stderr else "Claude Code failed"
            return default_hypothesis, output, error_text
        return extract_hypothesis(output, default_hypothesis), output, None

    if agent == "codex":
        output_file = Path(f"/tmp/autoresearch_codex_{experiment_num}.txt")
        result = subprocess.run(
            [
                "codex",
                "exec",
                "--full-auto",
                "--ephemeral",
                "--color",
                "never",
                "-C",
                str(Path.cwd()),
                "-o",
                str(output_file),
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = output_file.read_text(encoding="utf-8") if output_file.exists() else (result.stdout or "")
        if result.returncode != 0:
            error_text = result.stderr[:400] if result.stderr else "Codex CLI failed"
            return default_hypothesis, output, error_text
        return extract_hypothesis(output, default_hypothesis), output, None

    raise ValueError(f"Unsupported agent: {agent}")


def maybe_generate_corpus(corpus_manifest: Path, generate_script: Path | None) -> None:
    if corpus_manifest.exists():
        return
    if generate_script is None:
        print(f"ERROR: {corpus_manifest} not found.")
        print("Provide --generate-corpus-script or create the corpus first.")
        raise SystemExit(1)
    print(f"Corpus missing at {corpus_manifest}. Generating with {generate_script}...")
    result = subprocess.run(
        [sys.executable, str(generate_script)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0 or not corpus_manifest.exists():
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
        print(f"ERROR: corpus generation failed: {stderr}")
        raise SystemExit(1)


def build_config(args: argparse.Namespace) -> RunnerConfig:
    editable_files = tuple(
        Path(part.strip())
        for part in (args.editable_files.split(",") if args.editable_files else [args.editable_file])
        if part.strip()
    )
    return RunnerConfig(
        target_name=args.target_name,
        editable_files=editable_files,
        program_file=Path(args.program_file),
        eval_script=Path(args.eval_script),
        corpus_manifest=Path(args.corpus_manifest),
        log_file=Path(args.log_file),
        status_json_file=Path(args.status_json_file),
        status_md_file=Path(args.status_md_file),
        commit_prefix=args.commit_prefix,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex autoresearch loop")
    parser.add_argument("--max-experiments", type=int, default=DEFAULT_MAX_EXPERIMENTS)
    parser.add_argument(
        "--agent",
        choices=["claude", "codex", "manual"],
        default="manual",
        help="'claude' uses Claude Code; 'codex' uses Codex CLI; 'manual' pauses for human input",
    )
    parser.add_argument("--target", type=float, default=DEFAULT_TARGET_SCORE)
    parser.add_argument(
        "--agent-timeout",
        type=int,
        default=DEFAULT_AGENT_TIMEOUT,
        help="Max seconds to wait for a coding agent experiment",
    )
    parser.add_argument(
        "--no-improvement-limit",
        type=int,
        default=DEFAULT_NO_IMPROVEMENT_LIMIT,
        help="Stop after this many non-improving experiments in a row",
    )
    parser.add_argument("--target-name", default=DEFAULT_TARGET_NAME)
    parser.add_argument("--editable-file", default=str(DEFAULT_EDITABLE_FILE))
    parser.add_argument("--editable-files", default="")
    parser.add_argument("--program-file", default=str(DEFAULT_PROGRAM_FILE))
    parser.add_argument("--eval-script", default=str(DEFAULT_EVAL_SCRIPT))
    parser.add_argument("--corpus-manifest", default=str(DEFAULT_CORPUS_MANIFEST))
    parser.add_argument("--log-file", default=str(DEFAULT_LOG_FILE))
    parser.add_argument("--status-json-file", default=str(DEFAULT_STATUS_JSON_FILE))
    parser.add_argument("--status-md-file", default=str(DEFAULT_STATUS_MD_FILE))
    parser.add_argument("--commit-prefix", default=DEFAULT_COMMIT_PREFIX)
    parser.add_argument("--generate-corpus-script", default="")
    parser.add_argument(
        "--reset-history",
        action="store_true",
        help="Clear prior log/status files before starting a fresh run",
    )
    args = parser.parse_args()

    config = build_config(args)
    generate_corpus_script = Path(args.generate_corpus_script) if args.generate_corpus_script else None

    maybe_generate_corpus(config.corpus_manifest, generate_corpus_script)

    if not config.editable_files:
        print("ERROR: no editable files configured.")
        raise SystemExit(1)

    missing_files = [path for path in config.editable_files if not path.exists()]
    if missing_files:
        print(f"ERROR: missing editable files: {', '.join(str(path) for path in missing_files)}")
        print("Make sure you're running from the Cortex-AI repo root.")
        raise SystemExit(1)

    if not config.program_file.exists():
        print(f"ERROR: {config.program_file} not found.")
        raise SystemExit(1)

    if not config.eval_script.exists():
        print(f"ERROR: {config.eval_script} not found.")
        raise SystemExit(1)

    if args.reset_history:
        reset_run_files(config.log_file, config.status_json_file, config.status_md_file)

    print("Cortex Autoresearch Loop")
    print(f"Target name:    {config.target_name}")
    print(f"Editable file:  {format_editable_files(config.editable_files)}")
    print(f"Program file:   {config.program_file}")
    print(f"Eval script:    {config.eval_script}")
    print(f"Target score:   {args.target:.4f}")
    print(f"Max experiments: {args.max_experiments}")
    print(f"Agent mode:     {args.agent}\n")

    print("Computing baseline...")
    baseline = get_score(config.eval_script, quiet=True)
    if baseline is None:
        print("ERROR: baseline eval failed.")
        raise SystemExit(1)

    print(f"Baseline extraction_score: {baseline:.4f}\n")
    best = baseline
    no_improvement_streak = 0
    write_status(
        config,
        state="running",
        agent=args.agent,
        baseline=baseline,
        best=best,
        target=args.target,
        no_improvement_streak=no_improvement_streak,
    )

    if best >= args.target:
        print(f"Target {args.target:.4f} already met by baseline.")
        write_status(
            config,
            state="completed",
            agent=args.agent,
            baseline=baseline,
            best=best,
            target=args.target,
            no_improvement_streak=no_improvement_streak,
        )
        print_summary(config.log_file, config.target_name)
        return

    for exp_num in range(1, args.max_experiments + 1):
        print("-" * 55)
        print(f"Experiment {exp_num:03d}  |  Best so far: {best:.4f}")

        if args.agent == "manual":
            print(f"\nApply a change to {format_editable_files(config.editable_files)}, then press Enter to evaluate.")
            print("(Press Ctrl+C to stop the loop.)")
            try:
                hypothesis = input("Hypothesis: ").strip() or f"experiment {exp_num}"
            except KeyboardInterrupt:
                print("\nLoop interrupted by user.")
                break
        else:
            prompt = build_agent_prompt(exp_num, baseline, best, config)
            print(f"Invoking {args.agent} for experiment {exp_num}...")
            hypothesis, _output, error = run_agent(args.agent, prompt, exp_num, args.agent_timeout)
            if error:
                print(f"  {args.agent} failed: {error}")
                entry = {
                    "experiment": exp_num,
                    "timestamp": datetime.utcnow().isoformat(),
                    "hypothesis": hypothesis,
                    "score": None,
                    "delta": None,
                    "kept": False,
                    "reason": f"{args.agent}_failed",
                }
                log_experiment(config.log_file, entry)
                write_status(
                    config,
                    state="running",
                    agent=args.agent,
                    baseline=baseline,
                    best=best,
                    target=args.target,
                    no_improvement_streak=no_improvement_streak,
                    last_experiment=entry,
                )
                continue

        score = get_score(config.eval_script, quiet=True)
        if score is None:
            print("  EVAL FAILED - reverting")
            git_revert(config.editable_files)
            entry = {
                "experiment": exp_num,
                "timestamp": datetime.utcnow().isoformat(),
                "hypothesis": hypothesis,
                "score": None,
                "delta": None,
                "kept": False,
                "reason": "eval_failed",
            }
            log_experiment(config.log_file, entry)
            write_status(
                config,
                state="running",
                agent=args.agent,
                baseline=baseline,
                best=best,
                target=args.target,
                no_improvement_streak=no_improvement_streak,
                last_experiment=entry,
            )
            continue

        delta = score - best
        improved = delta > 0.001

        print(f"  Score: {score:.4f}  (delta: {delta:+.4f})")

        if improved:
            best = score
            no_improvement_streak = 0
            commit_message = (
                f"{config.commit_prefix} exp {exp_num:03d}: {hypothesis[:60]} "
                f"- score {score:.4f} ({delta:+.4f})"
            )
            git_commit(config.editable_files, commit_message)
            print(f"  KEPT ✓  New best: {best:.4f}")
        else:
            no_improvement_streak += 1
            git_revert(config.editable_files)
            print(f"  REVERTED  (no_improvement_streak: {no_improvement_streak})")

        entry = {
            "experiment": exp_num,
            "timestamp": datetime.utcnow().isoformat(),
            "hypothesis": hypothesis,
            "score": round(score, 4),
            "delta": round(delta, 4),
            "kept": improved,
        }
        log_experiment(config.log_file, entry)
        write_status(
            config,
            state="running",
            agent=args.agent,
            baseline=baseline,
            best=best,
            target=args.target,
            no_improvement_streak=no_improvement_streak,
            last_experiment=entry,
        )

        if best >= args.target:
            print(f"\nTarget {args.target:.4f} reached at experiment {exp_num}.")
            break
        if no_improvement_streak >= args.no_improvement_limit:
            print(f"\nStopped: {args.no_improvement_limit} consecutive experiments with no improvement.")
            break

    final_state = "completed" if best >= args.target else "stopped"
    experiments = load_experiments(config.log_file)
    write_status(
        config,
        state=final_state,
        agent=args.agent,
        baseline=baseline,
        best=best,
        target=args.target,
        no_improvement_streak=no_improvement_streak,
        last_experiment=experiments[-1] if experiments else None,
    )
    print_summary(config.log_file, config.target_name)


if __name__ == "__main__":
    main()
