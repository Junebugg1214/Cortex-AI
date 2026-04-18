#!/usr/bin/env python3
"""Animated terminal demo for Cortex audience-specific compilation."""

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
        self.rng = random.Random(19)
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
    store_dir = "/tmp/demo-audience/.cortex"

    demo.title("cortex — one graph, four audiences")

    demo.command('cortex mind init project-alpha --kind project --label "Project Alpha"')
    demo.output(
        [
            (f"Created Mind `project-alpha` at {store_dir}/minds/project-alpha", "OUT_GREEN"),
        ]
    )
    demo.blank()

    demo.comment("importing key facts from meeting_notes.txt")
    demo.command('cortex mind remember project-alpha "Project Alpha milestone: beta launch is May 1."')
    demo.output(
        [
            ("Mind `project-alpha` remembered:", "OUT_GREEN"),
            ("  Project Alpha milestone: beta launch is May 1.", "OUT_MID"),
            ("  branch main · 1 nodes · 0 edges", "OUT_MID"),
            ("  no persisted mounts to refresh.", "OUT_MID"),
        ]
    )
    demo.comment("importing key facts from architecture_decisions.md")
    demo.command('cortex mind remember project-alpha "Project Alpha decision: API gateway remains internal."')
    demo.output(
        [
            ("Mind `project-alpha` remembered:", "OUT_GREEN"),
            ("  Project Alpha decision: API gateway remains internal.", "OUT_MID"),
            ("  branch main · 2 nodes · 0 edges", "OUT_MID"),
            ("  no persisted mounts to refresh.", "OUT_MID"),
        ]
    )
    demo.blank()

    demo.comment("same graph, different disclosure per audience")
    for template, note in [
        ("executive", "executive: decisions + milestones only. Credentials hidden."),
        ("attorney", "attorney: full lineage. Disputed facts flagged."),
        ("onboarding", "onboarding: current state only. No history."),
        ("audit", "audit: complete graph. Every retraction logged."),
    ]:
        demo.command(f"cortex audience apply-template --mind project-alpha --template {template}")
        demo.output(
            [
                (f"Applied audience template `{template}` to Mind `project-alpha`", "OUT_GREEN"),
                ("Next:", "OUT_DIM"),
                (
                    f"  Preview the template output: cortex audience preview --mind project-alpha --audience {template} --store-dir {store_dir}",
                    "OUT_DIM",
                ),
                (
                    f"  Compile it when the preview looks right: cortex audience compile --mind project-alpha --audience {template} --store-dir {store_dir}",
                    "OUT_DIM",
                ),
            ]
        )
        demo.comment(note)
    demo.blank()

    demo.comment("compile all four — no copy-paste, no stale copies")
    compile_scenes = [
        (
            "executive",
            "  nodes: 27 -> 8",
            ["# Executive", "", "- Beta launch remains on track.", "- Technical implementation details were excluded."],
            "executive  → 8 nodes   (redacted: 19)",
        ),
        (
            "attorney",
            "  nodes: 27 -> 27",
            ["# Attorney", "", "- Full factual record included.", "- Source lineage is attached to exported facts."],
            "attorney   → 27 nodes  (redacted: 0)",
        ),
        (
            "onboarding",
            "  nodes: 27 -> 14",
            ["# Onboarding", "", "- Current state only.", "- Historical deltas were excluded."],
            "onboarding → 14 nodes  (redacted: 13)",
        ),
        (
            "audit",
            "  nodes: 27 -> 27",
            ["# Audit", "", "- Complete graph export ready.", "- Provenance included for all exported facts."],
            "audit      → 27 nodes  (redacted: 0, full provenance)",
        ),
    ]
    for audience, node_line, body, contrast in compile_scenes:
        demo.command(f"cortex audience compile --mind project-alpha --audience {audience}")
        lines: list[tuple[str, str]] = [
            (f"Compiled audience `{audience}` for Mind `project-alpha`", "OUT_GREEN"),
            (node_line, "OUT_MID"),
            ("", "OUT_MID"),
        ]
        lines.extend((item, "OUT_MID" if not item.startswith("#") else "OUT_DIM") for item in body)
        lines.extend(
            [
                ("Next:", "OUT_DIM"),
                (
                    f"  Preview the inclusion and redaction rules again: cortex audience preview --mind project-alpha --audience {audience} --store-dir {store_dir}",
                    "OUT_DIM",
                ),
                (
                    f"  Review compile history: cortex audience log --mind project-alpha --audience {audience} --store-dir {store_dir}",
                    "OUT_DIM",
                ),
            ]
        )
        demo.output(lines)
        demo.comment(contrast)
    demo.blank()

    demo.comment("conflict monitor catches what humans miss")
    demo.command("cortex admin agent monitor --once --mind project-alpha")
    demo.output(
        [
            ("Detected 1 conflicts; auto-resolved 0; queued 1.", "OUT_AMBER"),
        ]
    )
    demo.comment('HIGH conflict: "beta launch is May 1" vs "beta launch is June 1"')
    demo.comment("candidate 1: accept architecture_decisions.md (confidence 0.91)")
    demo.comment("candidate 2: accept meeting_notes.txt (confidence 0.84)")
    demo.comment("queued for review")
    demo.blank()
    demo.line("Same source. Different audiences.", color="OUT_PURP")
    demo.line("The graph knows what each one is allowed to see.", color="OUT_PURP")
    demo.sleep(1.5)
    demo.line("")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Cortex audience compilation demo.")
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
