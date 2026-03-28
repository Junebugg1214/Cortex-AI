from __future__ import annotations

import json
from pathlib import Path


def test_openclaw_plugin_manifest_matches_schema_example():
    root = Path(__file__).resolve().parents[1]
    example_dir = root / "examples" / "openclaw-plugin"

    manifest = json.loads((example_dir / "openclaw.plugin.json").read_text(encoding="utf-8"))
    schema = json.loads((example_dir / "config.schema.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "cortex"
    assert manifest["configSchema"] == schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["transport"]["default"] == "managed-child"
    assert schema["properties"]["defaultTarget"]["default"] == "chatgpt"
