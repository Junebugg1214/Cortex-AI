# Cortex + Manus

Cortex can work with Manus through a hosted custom MCP server.

The key constraint is that Manus expects a custom MCP server reachable over **HTTPS**, while `cortex-mcp` is a local stdio server. The `cortex-manus` bridge solves that by exposing a Manus-friendly HTTP MCP endpoint on top of Cortex's existing Mind, Brainpack, and portability tools.

## What the bridge exposes

By default, `cortex-manus` exposes a safe read-oriented toolset:

- `health`
- `meta`
- `portability_context`
- `portability_scan`
- `portability_status`
- `portability_audit`
- `mind_list`
- `mind_status`
- `mind_compose`
- `mind_mounts`
- `pack_list`
- `pack_status`
- `pack_context`
- `pack_query`
- `query_search`

Optional write tools can be enabled explicitly with `--allow-write-tools` and extra `--tool ...` flags.

## Why this is useful

Manus is strong at running long, multi-step agent work. Cortex gives it continuity.

Together, you can do things like:

- give Manus a composed Cortex Mind instead of a one-off prompt
- let Manus query Brainpacks as portable specialist cognition
- let Manus work against your portable AI context instead of restarting from zero in each session
- optionally let Manus write back into a Mind with explicit write-tool opt-in

## Run the bridge

Check the bridge first:

```bash
cortex-manus --config .cortex/config.toml --check
```

Run it locally:

```bash
cortex-manus --config .cortex/config.toml --host 127.0.0.1 --port 8790
```

You will see an MCP endpoint like:

```text
http://127.0.0.1:8790/mcp
```

For Manus, deploy or proxy that endpoint behind HTTPS.

## Enable write tools

The bridge is read-oriented by default. If you want Manus to update a Mind or Brainpack, opt in explicitly:

```bash
cortex-manus \
  --config .cortex/config.toml \
  --host 127.0.0.1 \
  --port 8790 \
  --allow-write-tools \
  --tool mind_mount
```

That adds the curated write-tool set:

- `mind_ingest`
- `mind_remember`
- `mind_mount`
- `pack_compile`
- `pack_ask`
- `pack_lint`
- `pack_mount`

## Connect it to Manus

In Manus:

1. go to `Settings -> Integrations -> Custom MCP Server`
2. click `Add server`
3. enter:
   - a server name such as `Cortex`
   - the HTTPS URL for your deployed bridge
   - the Bearer token or API key that matches your Cortex self-host config
4. test the connection

`cortex-manus` accepts the same API keys as the Cortex self-host config and supports:

- `Authorization: Bearer <token>`
- `X-API-Key: <token>`

## Recommended setup

For production:

- put the bridge behind HTTPS
- use scoped API keys
- prefer a pinned `--namespace` when serving a team or workflow-specific bridge
- keep the default read-oriented toolset unless you explicitly trust Manus to write back

## Novel Cortex + Manus workflows

### 1. Manus as a portable operator with a composed Mind

Manus can call `mind_compose` to get the right Cortex Mind for:

- a target runtime
- a task
- the attached Brainpacks that should activate for that task

That means Manus is no longer starting from scratch. It begins from a composed portable brain-state.

### 2. Manus as a Brainpack research worker

Manus can use:

- `pack_query`
- `pack_context`

to operate on Brainpacks as living domain minds, not just document piles.

### 3. Manus as a cross-platform continuity layer

Manus can inspect:

- `portability_context`
- `portability_status`
- `mind_status`

and reason from the same Cortex state your other AI tools already use.

### 4. Manus as a deliberate memory writer

If you enable write tools, Manus can:

- ingest detected context into a Mind
- remember new facts or preferences on a Mind
- trigger Brainpack maintenance

That makes Manus more than an external agent. It becomes a Cortex-connected operator with durable memory and specialist attachments.
