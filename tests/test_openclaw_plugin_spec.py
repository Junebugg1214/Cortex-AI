from __future__ import annotations

import json
from pathlib import Path


def test_openclaw_plugin_manifest_matches_schema_example():
    root = Path(__file__).resolve().parents[1]
    example_dir = root / "examples" / "openclaw-plugin"

    manifest = json.loads((example_dir / "openclaw.plugin.json").read_text(encoding="utf-8"))
    schema = json.loads((example_dir / "config.schema.json").read_text(encoding="utf-8"))
    package_json = json.loads((example_dir / "package.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "cortexai-openclaw"
    assert package_json["name"] == "cortexai-openclaw"
    assert package_json["displayName"] == "CortexAI OpenClaw"
    assert manifest["configSchema"] == schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["transport"]["default"] == "managed-child"
    assert schema["properties"]["defaultTarget"]["default"] == "chatgpt"
    assert schema["properties"]["maxContextChars"]["default"] == 1500
    assert schema["properties"]["failOpen"]["default"] is True
    assert schema["properties"]["serviceRestartLimit"]["default"] == 3
    assert "externalBaseUrl" not in schema["properties"]
    assert package_json["openclaw"]["extensions"] == ["./src/index.js"]
    assert package_json["publishConfig"]["access"] == "public"
    assert package_json["main"] == "./src/index.js"
    assert not list((example_dir / "src").glob("*.ts"))


def test_openclaw_docs_match_install_contract():
    root = Path(__file__).resolve().parents[1]
    quickstart = (root / "docs" / "OPENCLAW_QUICKSTART.md").read_text(encoding="utf-8")
    native = (root / "docs" / "OPENCLAW_NATIVE_PLUGIN.md").read_text(encoding="utf-8")
    readme = (root / "examples" / "openclaw-plugin" / "README.md").read_text(encoding="utf-8")

    docs = "\n".join([quickstart, native, readme])
    assert "/Users/marcsaint-jour" not in docs
    assert "cortexai-openclaw-1.4.1.tgz" not in docs
    assert 'TARBALL="$(npm pack --silent)"' in docs
    assert "--dangerously-force-unsafe-install" in docs
    assert "allowPromptInjection: true" in docs
    assert "allowConversationAccess: true" in docs
