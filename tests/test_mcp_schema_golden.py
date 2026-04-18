from __future__ import annotations

import hashlib
import json

from cortex.mcp.mcp_tools import MCPToolRegistry
from cortex.service import MemoryService


MCP_TOOLS_SORT_KEYS_SHA256 = "89566318da3a5541751b78177fb332b2a9a1f139a3ee9d03c1046e839e97d2f5"
MCP_TOOLS_SORT_KEYS_LENGTH = 58071


def test_mcp_tool_schema_golden_is_byte_identical_after_builder_split(tmp_path):
    service = MemoryService(store_dir=tmp_path / ".cortex")
    registry = MCPToolRegistry(service=service, effective_namespace=lambda value: value)

    canonical = json.dumps([tool.as_payload() for tool in registry.build()], sort_keys=True)

    assert len(canonical) == MCP_TOOLS_SORT_KEYS_LENGTH
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == MCP_TOOLS_SORT_KEYS_SHA256
