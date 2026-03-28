# OpenClaw Plugin Starter Spec

This directory is a starter spec for a future native OpenClaw plugin, not a published npm package yet.

It exists to make the Cortex + OpenClaw path concrete:

- [openclaw.plugin.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/openclaw.plugin.json)
- [config.schema.json](/Users/marcsaint-jour/Desktop/Cortex-AI/examples/openclaw-plugin/config.schema.json)
- [OpenClaw Native Plugin Spec](/Users/marcsaint-jour/Desktop/Cortex-AI/docs/OPENCLAW_NATIVE_PLUGIN.md)

The intended install UX is:

```bash
openclaw plugins install @cortex/openclaw
openclaw plugins enable cortex
openclaw gateway restart
```

The plugin should:

- start or connect to `cortex-mcp`
- fetch live routed context before prompt build
- seed per-user and per-thread memory after the turn
- keep Cortex self-hosted and user-owned

Phase 1 should ship as a normal plugin with hooks and a background service. It should not take over the exclusive OpenClaw `memory` slot until it also owns the `openclaw memory` surface directly.
