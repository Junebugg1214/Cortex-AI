from __future__ import annotations

import json
import os

import pytest

from cortex.atomic_io import atomic_write_json


def test_atomic_write_json_preserves_existing_file_on_replace_failure(tmp_path, monkeypatch):
    target = tmp_path / "payload.json"
    atomic_write_json(target, {"status": "old"})

    def fail_replace(src, dst):  # noqa: ARG001
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_json(target, {"status": "new"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "old"}
    assert not any(path.name.startswith(".payload.json.") for path in tmp_path.iterdir())
