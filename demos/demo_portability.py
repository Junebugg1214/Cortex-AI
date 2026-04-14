#!/usr/bin/env python3
"""Animated terminal demo for Cortex portability across AI tools."""

from __future__ import annotations

import argparse
import random
import sys
import time


def build_palette(is_tty: bool) -> dict[str, str]:
    if not is_tty:
        return {key: "" for key in COLORS}
    return dict(COLORS)


COLORS = {
    "PROMPT": "\033[38;5;99m",
    "CMD": "\033[97m",
    "OUT_DIM": "\033[38;5;240m",
    "OUT_MID": "\033[38;5;245m",
    "OUT_GREEN": "\033[38;5;40m",
    "OUT_AMBER": "\033[38;5;220m",
    "OUT_RED": "\033[38;5;196m",
    "OUT_CYAN": "\033[38;5;79m",
    "OUT_PURP": "\033[38;5;141m",
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
}


class Demo:
    """Small terminal animation helper."""

    def __init__(self, *, fast: bool) -> None:
        self.fast = fast
        self.scale = 0.2 if fast else 1.0
        self.rng = random.Random(7)
        self.is_tty = sys.stdout.isatty()
        self.colors = build_palette(self.is_tty)

    def sleep(self, minimum: float, maximum: float | None = None) -> None:
        duration = minimum if maximum is None else self.rng.uniform(minimum, maximum)
        time.sleep(duration * self.scale)

    def line(self, text: str = "", color: str = "OUT_MID") -> None:
        prefix = self.colors[color]
        suffix = self.colors["RESET"] if prefix else ""
        sys.stdout.write(f"{prefix}{text}{suffix}\n")
        sys.stdout.flush()

    def comment(self, text: str) -> None:
        self.line(f"# {text}", color="OUT_DIM")
        self.sleep(0.08, 0.15)

    def title(self, text: str) -> None:
        prefix = f"{self.colors['BOLD']}{self.colors['OUT_PURP']}"
        suffix = self.colors["RESET"] if self.is_tty else ""
        sys.stdout.write(f"{prefix}{text}{suffix}\n\n")
        sys.stdout.flush()
        self.sleep(0.4)

    def blank(self) -> None:
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.sleep(0.4)

    def command(self, text: str) -> None:
        sys.stdout.write(f"{self.colors['PROMPT']}~ {self.colors['RESET']}{self.colors['CMD']}")
        sys.stdout.flush()
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            self.sleep(0.02, 0.05)
        sys.stdout.write(f"{self.colors['RESET']}\n")
        sys.stdout.flush()
        self.sleep(0.08, 0.15)

    def output(self, lines: list[tuple[str, str]]) -> None:
        for text, color in lines:
            self.line(text, color=color)
            self.sleep(0.08, 0.15)


def run(fast: bool) -> int:
    demo = Demo(fast=fast)
    project_dir = "/tmp/demo-portability"
    home_dir = "/tmp/demo-home"

    demo.title("cortex — portable memory across AI tools")

    demo.command("cortex init")
    demo.output(
        [
            ("# Initialized Cortex at ./.cortex", "OUT_DIM"),
            ("#   config: ./.cortex/config.toml (created)", "OUT_DIM"),
            ("#   store source: default", "OUT_DIM"),
            ("#   default Mind: self (created)", "OUT_DIM"),
            ("#   auth keys: generated reader + writer tokens", "OUT_DIM"),
        ]
    )
    demo.blank()

    demo.command('cortex mind remember self "We use TypeScript and Supabase."')
    demo.output(
        [
            ("# Mind `self` remembered:", "OUT_DIM"),
            ("#   We use TypeScript and Supabase.", "OUT_DIM"),
            ("#   branch main · 3 nodes · 0 edges", "OUT_DIM"),
            ("#   no persisted mounts to refresh.", "OUT_DIM"),
        ]
    )
    demo.blank()

    demo.comment("mount the same Mind to three tools at once")
    demo.command('cortex mind mount self --to codex cursor claude-code --task "product strategy"')
    demo.output(
        [
            ("Mounted Mind `self`:", "OUT_GREEN"),
            ("  codex        ok  Updated 1 file(s)", "OUT_MID"),
            (f"    → {project_dir}/AGENTS.md", "OUT_MID"),
            ("  cursor       ok  Updated 1 file(s)", "OUT_MID"),
            (f"    → {project_dir}/.cursor/rules/cortex.mdc", "OUT_MID"),
            ("  claude-code  ok  Updated 2 file(s)", "OUT_MID"),
            (f"    → {home_dir}/.claude/CLAUDE.md", "OUT_MID"),
            (f"    → {project_dir}/CLAUDE.md", "OUT_MID"),
            ("  total persisted mounts: 3", "OUT_MID"),
            ("Next:", "OUT_DIM"),
            (
                f"  Inspect the persisted mount records: cortex mind mounts self --store-dir {project_dir}/.cortex",
                "OUT_DIM",
            ),
            (
                f"  Preview the exact routed slice: cortex mind compose self --to codex --store-dir {project_dir}/.cortex",
                "OUT_DIM",
            ),
        ]
    )
    demo.blank()

    demo.comment("switching from ChatGPT to Claude mid-project")
    demo.command("cortex switch --from chatgpt-export.zip --to claude --output portable --dry-run")
    demo.output(
        [
            ("Portable switch ready: openai -> claude", "OUT_GREEN"),
            ("  claude: portable/claude/claude_preferences.txt, portable/claude/claude_memories.json [dry-run]", "OUT_MID"),
        ]
    )
    demo.command("cortex switch --from chatgpt-export.zip --to claude --output portable")
    demo.output(
        [
            ("Portable switch ready: openai -> claude", "OUT_GREEN"),
            ("  claude: portable/claude/claude_preferences.txt, portable/claude/claude_memories.json [created]", "OUT_MID"),
        ]
    )
    demo.blank()

    demo.comment("something went wrong — roll back to yesterday")
    demo.command("cortex log --limit 3")
    demo.output(
        [
            ("* 9f8c2a4b7e1d3a66f1d25cf4303d5f1a  2026-04-13T18:42:11+00:00  [manual] (main)", "OUT_MID"),
            ("    Expand stack memory", "OUT_MID"),
            ("    nodes=6 edges=0", "OUT_MID"),
            ("* 65fc26accf0373d4d8990f24341c9263  2026-04-12T14:29:58+00:00  [manual] (main)", "OUT_MID"),
            ("    Initial memory snapshot", "OUT_MID"),
            ("    nodes=5 edges=0", "OUT_MID"),
            ("* aa0af1625b548afc315bbf32c17e15c1  2026-04-11T08:15:02+00:00  [extract] (main)", "OUT_MID"),
            ("    Imported ChatGPT export", "OUT_MID"),
            ("    nodes=4 edges=0", "OUT_MID"),
        ]
    )
    demo.command("cortex rollback context.json --at 2026-04-12T14:30:00Z")
    demo.output(
        [
            (
                "Rolled back main to 65fc26accf0373d4d8990f24341c9263 as new commit b7e2aa99c14d56cb0e9ab2dd88f1d7c4.",
                "OUT_GREEN",
            ),
            ("  Wrote restored graph to context.json", "OUT_MID"),
        ]
    )
    demo.blank()
    demo.line("One Mind. Every tool. Always current.", color="OUT_PURP")
    demo.line("No vendor owns your memory.", color="OUT_PURP")
    demo.sleep(1.5)
    demo.line("")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Cortex portability demo.")
    parser.add_argument("--fast", action="store_true", help="Reduce delays for quick previews.")
    args = parser.parse_args()
    try:
        return run(args.fast)
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
