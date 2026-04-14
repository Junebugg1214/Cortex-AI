#!/usr/bin/env python3
"""Animated terminal demo for Cortex source-safe retraction."""

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
        self.rng = random.Random(42)
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

    def progress(
        self,
        label: str,
        total: int,
        final_bar: str,
        *,
        count_text: str,
        color: str = "OUT_CYAN",
    ) -> None:
        if not self.is_tty:
            self.line(f"{label}{final_bar}{count_text}", color=color)
            self.sleep(0.08, 0.15)
            return
        width = len(final_bar) - 2
        for step in range(total + 1):
            if step >= total:
                bar = final_bar
                count = count_text
            else:
                filled = round(width * (step / total)) if total else width
                bar = "[" + "=" * filled + " " * (width - filled) + "]"
                count = f" {step}/{total}"
            sys.stdout.write(
                f"\r{self.colors[color]}{label}{bar}{count}{self.colors['RESET']}"
            )
            sys.stdout.flush()
            self.sleep(0.05, 0.11)
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.sleep(0.08, 0.15)


def run(fast: bool) -> int:
    demo = Demo(fast=fast)
    stable_id = "4f3aa71d8f8f2dd1d733f1f2f17b9c11c44e5fc9f0b0d8b6216309b4f28ac91e"
    store_dir = "/tmp/demo-retraction/.cortex"

    demo.title("cortex — surgical retraction")

    demo.comment("create the Mind that owns this compliance graph")
    demo.command('cortex mind init compliance-kb --kind project --label "Compliance KB"')
    demo.output(
        [
            (f"Created Mind `compliance-kb` at {store_dir}/minds/compliance-kb", "OUT_GREEN"),
        ]
    )
    demo.blank()

    demo.comment("demo fixture: policy_v3.pdf is already registered on this Mind")
    demo.command("cortex sources list --mind compliance-kb")
    demo.output(
        [
            ("Mind `compliance-kb` sources", "OUT_MID"),
            (f"  {stable_id} (policy_v3.pdf)", "OUT_MID"),
            ("Next:", "OUT_DIM"),
            (
                f"  Preview a retraction safely: cortex sources retract {stable_id} --mind compliance-kb --dry-run --store-dir {store_dir}",
                "OUT_DIM",
            ),
        ]
    )
    demo.blank()

    demo.command("cortex audience apply-template --mind compliance-kb --template executive")
    demo.output(
        [
            ("Applied audience template `executive` to Mind `compliance-kb`", "OUT_GREEN"),
            ("Next:", "OUT_DIM"),
            (
                f"  Preview the template output: cortex audience preview --mind compliance-kb --audience executive --store-dir {store_dir}",
                "OUT_DIM",
            ),
            (
                f"  Compile it when the preview looks right: cortex audience compile --mind compliance-kb --audience executive --store-dir {store_dir}",
                "OUT_DIM",
            ),
        ]
    )
    demo.command("cortex audience compile --mind compliance-kb --audience executive")
    demo.output(
        [
            ("Compiled audience `executive` for Mind `compliance-kb`", "OUT_GREEN"),
            ("  nodes: 14 -> 6", "OUT_MID"),
            ("", "OUT_MID"),
            ("# Executive", "OUT_DIM"),
            ("", "OUT_MID"),
            ("- Retention policy update is active.", "OUT_MID"),
            ("- Credential-bearing facts were excluded by audience policy.", "OUT_MID"),
        ]
    )
    demo.blank()

    demo.comment("6 hours later — source flagged as incorrect")
    demo.command("cortex sources retract policy_v3.pdf --mind compliance-kb --dry-run")
    demo.output(
        [
            (f"Previewing source {stable_id} on Mind `compliance-kb`", "OUT_AMBER"),
            ("  labels: policy_v3.pdf", "OUT_MID"),
            ("  nodes pruned: 14", "OUT_MID"),
            ("  edges pruned: 2", "OUT_MID"),
            ("Next:", "OUT_DIM"),
            (
                f"  Apply this retraction: cortex sources retract {stable_id} --mind compliance-kb --confirm --store-dir {store_dir}",
                "OUT_DIM",
            ),
            (
                f"  List the current lineage again: cortex sources list --mind compliance-kb --store-dir {store_dir}",
                "OUT_DIM",
            ),
        ]
    )
    demo.comment("no orphaned nodes remain in the retraction plan")
    demo.blank()

    demo.command("cortex sources retract policy_v3.pdf --mind compliance-kb --confirm")
    demo.progress("Pruning facts...           ", 14, "[==============]", count_text=" 14/14")
    demo.progress(
        "Retracting claims...       ",
        3,
        "[===========  ]",
        count_text="  3/3",
        color="OUT_AMBER",
    )
    demo.progress("Removing relationships...  ", 2, "[=============]", count_text="  2/2")
    demo.progress(
        "Invalidating artifacts...  ",
        2,
        "[=============]",
        count_text="  2/2",
        color="OUT_PURP",
    )
    demo.output(
        [
            (f"Retracted source {stable_id} on Mind `compliance-kb`", "OUT_GREEN"),
            ("  labels: policy_v3.pdf", "OUT_MID"),
            ("  nodes pruned: 14", "OUT_MID"),
            ("  edges pruned: 2", "OUT_MID"),
            ("Next:", "OUT_DIM"),
            (
                f"  Verify the remaining lineage: cortex sources list --mind compliance-kb --store-dir {store_dir}",
                "OUT_DIM",
            ),
            (f"  Run an integrity check: cortex integrity check --store-dir {store_dir}", "OUT_DIM"),
        ]
    )
    demo.blank()

    demo.command("cortex integrity check")
    demo.output(
        [
            ("✓ lineage intact", "OUT_GREEN"),
            ("✓ version chain intact", "OUT_GREEN"),
            ("✓ no orphaned nodes", "OUT_GREEN"),
            ("✓ no retracted-source references", "OUT_GREEN"),
            ("Integrity check: OK", "OUT_GREEN"),
            (f"  Store: {store_dir}", "OUT_MID"),
            ("  Current branch: main", "OUT_MID"),
            ("  Head: 8a2bc11d4f5e9037b4e2f0d19f4703c1", "OUT_MID"),
            ("  No integrity issues detected.", "OUT_MID"),
        ]
    )
    demo.blank()
    demo.line("A vector DB deletes the file.", color="OUT_PURP")
    demo.line("These facts would still be answering queries.", color="OUT_PURP")
    demo.sleep(1.5)
    demo.line("")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Cortex surgical retraction demo.")
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
