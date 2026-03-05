# Cortex

Own your AI ID.

Cortex is a CLI-first toolkit for portable AI memory and identity.
You control your data and run it on your own infrastructure.

## Open Source Scope

- CLI + self-host workflows
- No hosted data model in this release
- Designed for developer-owned storage and portability

## Install

```bash
pip install cortex-identity
```

Extras:

```bash
pip install cortex-identity[crypto]
pip install cortex-identity[fast]
pip install cortex-identity[postgres]
pip install cortex-identity[full]
```

## CLI Quickstart

```bash
# Build graph from export
cortex extract <export-file> -o context.json

# Inspect
cortex stats context.json

# Export to target formats
cortex import context.json --to all -o ./output
```

## Common Commands

```bash
cortex extract <file> -o context.json
cortex import context.json --to claude -o ./output
cortex query context.json --node "Python"
cortex timeline context.json --format md
cortex contradictions context.json
cortex identity --init --name "Your Name"
```

## Documentation

- Python quickstart: `docs/quickstart-python.md`
- Security model: `docs/security.md`
- Threat model: `docs/threat-model.md`
- API spec: `spec/openapi.json`

## License

MIT
