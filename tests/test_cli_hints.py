from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_doctor_hint_without_admin_namespace() -> None:
    offenders = []
    for path in REPO_ROOT.rglob("*.py"):
        if path.is_relative_to(REPO_ROOT / "tests"):
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "cortex doctor" in line and "cortex admin doctor" not in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}")
    assert offenders == [], "Use `cortex admin doctor` in user-facing hints:\n" + "\n".join(offenders)
