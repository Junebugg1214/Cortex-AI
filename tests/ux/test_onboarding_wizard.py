from __future__ import annotations

import pytest

from cortex.onboarding.wizard import (
    OnboardingWizardError,
    complete_wizard,
    is_complete,
    load_wizard_state,
    record_compile,
    record_source,
    reset_wizard,
    skip_wizard,
    start_wizard,
)


def test_wizard_creates_default_pending_state(tmp_path):
    state = load_wizard_state(tmp_path / ".cortex")

    assert state["status"] == "pending"
    assert state["step"] == "welcome"
    assert state["skipped"] is False


def test_wizard_advances_through_create_source_and_compile(tmp_path):
    store_dir = tmp_path / ".cortex"

    started = start_wizard(store_dir, mind_id="ops", mind_label="Ops")
    imported = record_source(store_dir, source_kind="paste", source_value="Project Atlas launched")
    compiled = record_compile(store_dir, audience_template="executive", result_summary="Executive brief ready.")

    assert started["step"] == "mind"
    assert imported["step"] == "compile"
    assert compiled["status"] == "complete"
    assert compiled["step"] == "result"
    assert is_complete(store_dir) is True


def test_wizard_skip_is_persistent(tmp_path):
    store_dir = tmp_path / ".cortex"

    skipped = skip_wizard(store_dir)
    reloaded = load_wizard_state(store_dir)

    assert skipped["status"] == "complete"
    assert skipped["skipped"] is True
    assert reloaded["skipped"] is True


def test_wizard_reset_returns_to_initial_state(tmp_path):
    store_dir = tmp_path / ".cortex"
    start_wizard(store_dir, mind_id="ops", mind_label="Ops")

    reset = reset_wizard(store_dir)

    assert reset["status"] == "pending"
    assert reset["step"] == "welcome"
    assert is_complete(store_dir) is False


def test_wizard_rejects_source_changes_after_completion(tmp_path):
    store_dir = tmp_path / ".cortex"
    complete_wizard(store_dir, summary="Finished")

    with pytest.raises(OnboardingWizardError, match="already complete"):
        record_source(store_dir, source_kind="file", source_value="/tmp/incident.md")

