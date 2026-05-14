# Cortex + Hermes Integration

Verified on 2026-05-14 against the local Cortex repo and upstream Hermes Agent docs/source.

| Hermes agent capability | What Cortex adds | Integration proof |
| --- | --- | --- |
| Persistent `USER.md` and `MEMORY.md` files | A canonical, portable Cortex graph that syncs into Hermes-native memory files without overwriting human text | `cortex sync --to hermes`, `install_hermes_context`, non-destructive marker tests |
| `mcp_servers` in `config.yaml` | Managed `cortex-mcp` wiring so Hermes can call live Cortex context tools | `cortex connect hermes --install --check`, MCP config scan tests |
| Multiple Hermes profiles via `HERMES_HOME` and `~/.hermes/active_profile` | Profile-aware installs so Cortex mounts into the active Hermes agent, not the wrong default home | Added `cortex/hermes_paths.py` and profile regression coverage |
| Runtime-local agent memory | Cross-tool continuity: the same context can mount into Hermes, Codex, Cursor, Claude Code, OpenClaw, and MCP clients | Portability target matrix and smart sync flows |
| Agent-managed memories and external providers | Source-aware context adoption, audit, and explicit sync controls before facts become runtime memory | `scan`, `portable --from-detected`, `remember`, and `sync --smart` workflows |
| Long-running agents and messaging gateways | A shared context layer for channel agents, preserving identity/thread namespaces outside one runtime | `ChannelContextBridge` docs and Hermes + Cortex channel flow |

## Tweet Draft

Hermes gives agents a real runtime: tools, MCP, profiles, memory, gateways.

Cortex now plugs into Hermes as the portable context layer:
- syncs the canonical graph into `USER.md` / `MEMORY.md`
- wires `cortex-mcp` into `config.yaml`
- respects `HERMES_HOME` + active profiles
- keeps the same context usable across Codex, Cursor, Claude Code, OpenClaw, and Hermes

Not "more memory." Portable agent continuity.

