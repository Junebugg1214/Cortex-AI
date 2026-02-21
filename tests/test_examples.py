"""Tests for examples/ — validate example application structure and imports."""

from __future__ import annotations

import ast
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


class TestExampleStructure:
    def test_chatbot_memory_exists(self):
        assert (EXAMPLES_DIR / "chatbot-memory" / "main.py").exists()
        assert (EXAMPLES_DIR / "chatbot-memory" / "README.md").exists()

    def test_multi_agent_exists(self):
        assert (EXAMPLES_DIR / "multi-agent" / "main.py").exists()
        assert (EXAMPLES_DIR / "multi-agent" / "README.md").exists()

    def test_sdk_quickstart_exists(self):
        assert (EXAMPLES_DIR / "sdk-quickstart" / "main.py").exists()
        assert (EXAMPLES_DIR / "sdk-quickstart" / "README.md").exists()


class TestExampleSyntax:
    """Verify all example files are valid Python."""

    def test_chatbot_memory_parses(self):
        source = (EXAMPLES_DIR / "chatbot-memory" / "main.py").read_text()
        ast.parse(source)

    def test_multi_agent_parses(self):
        source = (EXAMPLES_DIR / "multi-agent" / "main.py").read_text()
        ast.parse(source)

    def test_sdk_quickstart_parses(self):
        source = (EXAMPLES_DIR / "sdk-quickstart" / "main.py").read_text()
        ast.parse(source)


class TestExampleContent:
    def test_chatbot_memory_has_main(self):
        source = (EXAMPLES_DIR / "chatbot-memory" / "main.py").read_text()
        assert "def main" in source
        assert '__name__ == "__main__"' in source

    def test_multi_agent_has_main(self):
        source = (EXAMPLES_DIR / "multi-agent" / "main.py").read_text()
        assert "def main" in source
        assert "GrantToken" in source
        assert "UPAIIdentity" in source

    def test_sdk_quickstart_has_main(self):
        source = (EXAMPLES_DIR / "sdk-quickstart" / "main.py").read_text()
        assert "def main" in source
        assert "CortexClient" in source

    def test_chatbot_memory_imports_cortex(self):
        source = (EXAMPLES_DIR / "chatbot-memory" / "main.py").read_text()
        assert "from cortex" in source

    def test_multi_agent_imports_upai(self):
        source = (EXAMPLES_DIR / "multi-agent" / "main.py").read_text()
        assert "from cortex.upai" in source


class TestExampleReadmes:
    def test_chatbot_readme_has_run_instructions(self):
        text = (EXAMPLES_DIR / "chatbot-memory" / "README.md").read_text()
        assert "python" in text.lower()

    def test_multi_agent_readme_has_concepts(self):
        text = (EXAMPLES_DIR / "multi-agent" / "README.md").read_text()
        assert "Grant" in text or "grant" in text

    def test_sdk_quickstart_readme_has_api_table(self):
        text = (EXAMPLES_DIR / "sdk-quickstart" / "README.md").read_text()
        assert "client" in text.lower()
