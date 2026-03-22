#!/usr/bin/env python3
"""
Cortex Autoresearch — Loop Runner

Runs the agent in a git-disciplined eval/commit/revert cycle.
Designed to work with Claude Code, Codex, or any coding agent
that can read program.md and modify cortex/extract_memory.py.

Usage:
  python autoresearch.py                    # Interactive (human or agent applies changes)
  python autoresearch.py --agent claude     # Automated with Claude Code
  python autoresearch.py --max-experiments 25
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("autoresearch_log.jsonl")
TARGET_SCORE = 0.92
MAX_EXPERIMENTS = 50
NO_IMPROVEMENT_LIMIT = 10
EDITABLE_FILE = "cortex/extract_memory.py"


# ─── Git Helpers ──────────────────────────────────────────────────────────────

def git_commit(message: str) -> bool:
    r1 = subprocess.run(["git", "add", EDITABLE_FILE], capture_output=True)
    r2 = subprocess.run(["git", "commit", "-m", message], capture_output=True)
    return r2.returncode == 0


def git_revert():
    subprocess.run(["git", "checkout", EDITABLE_FILE], capture_output=True)


def git_stash_state() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip()


# ─── Score Runner ─────────────────────────────────────────────────────────────

def get_score(quiet: bool = True) -> float | None:
    flag = ["--quiet"] if quiet else []
    result = subprocess.run(
        ["python", "eval.py"] + flag,
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return None
    try:
        last_line = result.stdout.strip().splitlines()[-1]
        return float(last_line.split()[-1])
    except (ValueError, IndexError):
        return None


# ─── Logger ───────────────────────────────────────────────────────────────────

def log_experiment(entry: dict):
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def print_summary(log_path: Path):
    if not log_path.exists():
        return
    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    kept = [e for e in entries if e.get("kept")]
    print(f"\n{'═'*55}")
    print(f"  Autoresearch complete")
    print(f"  Experiments run:  {len(entries)}")
    print(f"  Improvements kept: {len(kept)}")
    if kept:
        total_gain = sum(e["delta"] for e in kept)
        print(f"  Total score gain: +{total_gain:.4f}")
        print(f"  Best experiment:  exp {max(kept, key=lambda e: e['delta'])['experiment']}")
    print(f"{'═'*55}")


# ─── Agent Prompt ─────────────────────────────────────────────────────────────

def build_agent_prompt(experiment_num: int, baseline: float, current_best: float) -> str:
    return f"""You are running experiment {experiment_num} of the Cortex autoresearch loop.

Current best extraction_score: {current_best:.4f}
Baseline score: {baseline:.4f}

Read program.md for full instructions and known weak areas.
Your task:
1. Read cortex/extract_memory.py
2. Form one hypothesis for improvement (see program.md for suggestions)
3. Apply the change to cortex/extract_memory.py ONLY
4. Do not run eval.py yourself — the loop runner will do it

State your hypothesis clearly before making the change.
Make exactly one change. Do not touch any other file.
"""


# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cortex autoresearch loop")
    parser.add_argument("--max-experiments", type=int, default=MAX_EXPERIMENTS)
    parser.add_argument("--agent", choices=["claude", "manual"], default="manual",
                        help="'claude' uses Claude Code; 'manual' pauses for human/agent input")
    parser.add_argument("--target", type=float, default=TARGET_SCORE)
    args = parser.parse_args()

    # Verify corpus exists
    if not Path("corpus/manifest.json").exists():
        print("ERROR: corpus/manifest.json not found.")
        print("Run: python generate_corpus.py")
        sys.exit(1)

    # Verify editable file exists
    if not Path(EDITABLE_FILE).exists():
        print(f"ERROR: {EDITABLE_FILE} not found.")
        print("Make sure you're running from the Cortex-AI repo root.")
        sys.exit(1)

    print("Cortex Autoresearch Loop")
    print(f"Editable file:  {EDITABLE_FILE}")
    print(f"Target score:   {args.target:.4f}")
    print(f"Max experiments: {args.max_experiments}")
    print(f"Agent mode:     {args.agent}\n")

    # Establish baseline
    print("Computing baseline...")
    baseline = get_score(quiet=True)
    if baseline is None:
        print("ERROR: eval.py failed on baseline run. Check cortex installation.")
        sys.exit(1)

    print(f"Baseline extraction_score: {baseline:.4f}\n")
    best = baseline
    no_improvement_streak = 0

    for exp_num in range(1, args.max_experiments + 1):
        print(f"{'─'*55}")
        print(f"Experiment {exp_num:03d}  |  Best so far: {best:.4f}")

        if args.agent == "manual":
            print(f"\nApply a change to {EDITABLE_FILE}, then press Enter to evaluate.")
            print("(Press Ctrl+C to stop the loop.)")
            try:
                hypothesis = input("Hypothesis: ").strip() or f"experiment {exp_num}"
            except KeyboardInterrupt:
                print("\nLoop interrupted by user.")
                break

        elif args.agent == "claude":
            # Invoke Claude Code with the experiment prompt
            prompt = build_agent_prompt(exp_num, baseline, best)
            prompt_file = Path(f"/tmp/autoresearch_prompt_{exp_num}.txt")
            prompt_file.write_text(prompt)
            print(f"Invoking Claude Code for experiment {exp_num}...")
            result = subprocess.run(
                ["claude", "--print", prompt_file.read_text()],
                capture_output=True, text=True, timeout=300
            )
            hypothesis = f"claude_exp_{exp_num}"
            if result.returncode != 0:
                print(f"  Claude Code failed: {result.stderr[:200]}")
                continue

        # Evaluate
        score = get_score(quiet=True)
        if score is None:
            print(f"  EVAL FAILED — reverting")
            git_revert()
            log_experiment({
                "experiment": exp_num,
                "timestamp": datetime.utcnow().isoformat(),
                "hypothesis": hypothesis,
                "score": None,
                "delta": None,
                "kept": False,
                "reason": "eval_failed"
            })
            continue

        delta = score - best
        improved = delta > 0.001  # Require meaningful improvement

        print(f"  Score: {score:.4f}  (delta: {delta:+.4f})")

        if improved:
            best = score
            no_improvement_streak = 0
            git_commit(f"autoresearch exp {exp_num:03d}: {hypothesis[:60]} — score {score:.4f} ({delta:+.4f})")
            print(f"  KEPT ✓  New best: {best:.4f}")
        else:
            no_improvement_streak += 1
            git_revert()
            print(f"  REVERTED  (no_improvement_streak: {no_improvement_streak})")

        log_experiment({
            "experiment": exp_num,
            "timestamp": datetime.utcnow().isoformat(),
            "hypothesis": hypothesis,
            "score": round(score, 4),
            "delta": round(delta, 4),
            "kept": improved,
        })

        # Stopping criteria
        if best >= args.target:
            print(f"\nTarget {args.target:.4f} reached at experiment {exp_num}.")
            break
        if no_improvement_streak >= NO_IMPROVEMENT_LIMIT:
            print(f"\nStopped: {NO_IMPROVEMENT_LIMIT} consecutive experiments with no improvement.")
            break

    print_summary(LOG_FILE)


if __name__ == "__main__":
    main()
