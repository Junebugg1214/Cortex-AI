# MCP Example

Use the same local, user-owned Cortex store with an MCP client by launching:

```bash
cortex-mcp --config .cortex/config.toml
```

For Claude Desktop, point your client config at the shared example in
[docs/examples/claude_desktop_mcp.json](../../docs/examples/claude_desktop_mcp.json).

The simplest smoke test is to send newline-delimited JSON-RPC messages over stdio:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","clientInfo":{"name":"local-test","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"query_search","arguments":{"query":"atlas","limit":5}}}
```

That MCP surface maps onto the same object, query, merge, index, and prune runtime used by the REST API.
