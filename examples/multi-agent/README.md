# Multi-Agent Context Sharing Example

Demonstrates how multiple AI agents can share context through scoped grants:

- **Agent A**: Read-only access to context and identity
- **Agent B**: Read-write access for context mutations

## Run

```bash
python examples/multi-agent/main.py
```

## Key Concepts

- **UPAI Identity**: Ed25519 keypair with DID identifier
- **Grant Tokens**: Scoped, time-limited tokens for API access
- **RBAC**: 10 scopes across 4 roles (owner, admin, editor, reader)
