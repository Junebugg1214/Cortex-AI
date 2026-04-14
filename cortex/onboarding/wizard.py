"""Persistent first-run onboarding state for Cortex.

The wizard is intentionally simple: it tracks the user's progress through the
first useful flow, stores that state in the local Cortex store, and exposes a
small set of transitions that the UI can drive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal

from cortex.atomic_io import atomic_write_json, locked_path

WizardStatus = Literal["pending", "in_progress", "complete"]
WizardStep = Literal["welcome", "mind", "source", "compile", "result"]
SourceKind = Literal["file", "url", "paste"]


class OnboardingWizardError(ValueError):
    """Raised when the wizard state machine receives an invalid transition."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def wizard_state_path(store_dir: str | Path) -> Path:
    """Return the JSON file used to persist onboarding progress."""
    return Path(store_dir) / "onboarding" / "wizard.json"


def _default_state() -> dict[str, Any]:
    return {
        "status": "pending",
        "step": "welcome",
        "skipped": False,
        "mind_id": "",
        "mind_label": "",
        "source_kind": "",
        "source_value": "",
        "audience_template": "",
        "result_summary": "",
        "completed_at": "",
        "updated_at": _iso_now(),
    }


def _ensure_state_shape(payload: dict[str, Any]) -> dict[str, Any]:
    state = _default_state()
    state.update(payload)
    state["status"] = str(state["status"] or "pending")
    state["step"] = str(state["step"] or "welcome")
    state["skipped"] = bool(state["skipped"])
    return state


def load_wizard_state(store_dir: str | Path) -> dict[str, Any]:
    """Load the persisted onboarding state, creating a default one if absent."""
    path = wizard_state_path(store_dir)
    if not path.exists():
        state = _default_state()
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked_path(path):
            atomic_write_json(path, state)
        return state
    return _ensure_state_shape(json.loads(path.read_text(encoding="utf-8")))


def save_wizard_state(store_dir: str | Path, state: dict[str, Any]) -> dict[str, Any]:
    """Persist onboarding state and return the stored payload."""
    path = wizard_state_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _ensure_state_shape(state)
    payload["updated_at"] = _iso_now()
    with locked_path(path):
        atomic_write_json(path, payload)
    return payload


def summarize_wizard_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a UI-friendly summary for the current wizard state."""
    step = str(state.get("step") or "welcome")
    next_step = {
        "welcome": "mind",
        "mind": "source",
        "source": "compile",
        "compile": "result",
        "result": "complete",
    }.get(step, "complete")
    return {
        "status": str(state.get("status") or "pending"),
        "step": step,
        "next_step": next_step,
        "skipped": bool(state.get("skipped")),
        "mind_id": str(state.get("mind_id") or ""),
        "mind_label": str(state.get("mind_label") or ""),
        "source_kind": str(state.get("source_kind") or ""),
        "source_value": str(state.get("source_value") or ""),
        "audience_template": str(state.get("audience_template") or ""),
        "result_summary": str(state.get("result_summary") or ""),
        "completed_at": str(state.get("completed_at") or ""),
        "updated_at": str(state.get("updated_at") or ""),
        "title": {
            "welcome": "Name your first Mind",
            "mind": "Ingest one source",
            "source": "Compile your first output",
            "compile": "Review the result",
            "result": "You're done",
        }.get(step, "Onboarding"),
    }


def start_wizard(store_dir: str | Path, *, mind_id: str, mind_label: str = "") -> dict[str, Any]:
    """Start or resume onboarding for a Mind."""
    state = save_wizard_state(
        store_dir,
        {
            **load_wizard_state(store_dir),
            "status": "in_progress",
            "step": "mind",
            "mind_id": mind_id,
            "mind_label": mind_label or mind_id,
            "skipped": False,
        },
    )
    return summarize_wizard_state(state)


def record_source(
    store_dir: str | Path,
    *,
    source_kind: SourceKind,
    source_value: str,
) -> dict[str, Any]:
    """Record the first imported source for the onboarding flow."""
    state = load_wizard_state(store_dir)
    if state.get("status") == "complete":
        raise OnboardingWizardError("The onboarding wizard is already complete.")
    state["status"] = "in_progress"
    state["step"] = "compile"
    state["source_kind"] = source_kind
    state["source_value"] = source_value.strip()
    return summarize_wizard_state(save_wizard_state(store_dir, state))


def record_compile(
    store_dir: str | Path,
    *,
    audience_template: str,
    result_summary: str,
) -> dict[str, Any]:
    """Record the first compiled output and advance the wizard."""
    state = load_wizard_state(store_dir)
    if state.get("status") == "complete":
        raise OnboardingWizardError("The onboarding wizard is already complete.")
    state["status"] = "complete"
    state["step"] = "result"
    state["audience_template"] = audience_template
    state["result_summary"] = result_summary.strip()
    state["completed_at"] = _iso_now()
    state["skipped"] = False
    return summarize_wizard_state(save_wizard_state(store_dir, state))


def complete_wizard(store_dir: str | Path, *, summary: str = "") -> dict[str, Any]:
    """Mark the wizard complete without changing the recorded steps."""
    state = load_wizard_state(store_dir)
    state["status"] = "complete"
    state["step"] = "result"
    state["result_summary"] = summary.strip() or str(state.get("result_summary") or "")
    state["completed_at"] = state.get("completed_at") or _iso_now()
    return summarize_wizard_state(save_wizard_state(store_dir, state))


def skip_wizard(store_dir: str | Path) -> dict[str, Any]:
    """Skip onboarding and persist that choice."""
    state = load_wizard_state(store_dir)
    state["status"] = "complete"
    state["step"] = "result"
    state["skipped"] = True
    state["completed_at"] = _iso_now()
    if not state.get("result_summary"):
        state["result_summary"] = "Skipped during first run."
    return summarize_wizard_state(save_wizard_state(store_dir, state))


def reset_wizard(store_dir: str | Path) -> dict[str, Any]:
    """Reset onboarding back to its initial state."""
    path = wizard_state_path(store_dir)
    if path.exists():
        path.unlink()
    return summarize_wizard_state(load_wizard_state(store_dir))


def is_complete(store_dir: str | Path) -> bool:
    """Return whether onboarding has been completed or skipped."""
    return str(load_wizard_state(store_dir).get("status") or "") == "complete"


__all__ = [
    "OnboardingWizardError",
    "WizardStatus",
    "WizardStep",
    "SourceKind",
    "complete_wizard",
    "is_complete",
    "load_wizard_state",
    "record_compile",
    "record_source",
    "reset_wizard",
    "save_wizard_state",
    "skip_wizard",
    "start_wizard",
    "summarize_wizard_state",
    "wizard_state_path",
]
