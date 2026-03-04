# Cortex

Own your AI ID.

Cortex is a self-host-first platform for portable AI memory and identity.
Your memory/context belongs to you, lives on your infrastructure, and can be shared in scoped formats (`professional`, `technical`, etc.) instead of all-or-nothing dumps.

## Product Direction

- Self-host only storage model (no BYOS, no local-vault mode in consumer flow)
- Connector-first UX for continuity across AI tools
- Scoped sharing controls and policy-based exports
- Consumer Mode for non-technical users

## Beta Website

- Web app: [https://gollumgo.com/app](https://gollumgo.com/app)

Use the beta website to test UX and flow.
For real data ownership/privacy guarantees, run your own self-host instance.

## Core Flow (Web App)

1. Open `/app` and create an account
2. Add connectors
3. Sync memory/context
4. Review memory graph and summaries
5. Share selected slices (professional/technical/minimal/full)

## One-Command Self-Host Starter

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git && cd Cortex-AI && CORTEX_REF=ae5b9d0b57e00aa27ac8d46bd635e9325934ca97 bash deploy/self-host-starter.sh
```

After install:

1. Open your own `/app` URL
2. Create your account on your own server
3. Connect tools, import/sync memory, and share scoped views

Private repo fallback:

```bash
CORTEX_REPO_URL=git@github.com:Junebugg1214/Cortex-AI.git CORTEX_REF=<tag-or-commit> bash deploy/self-host-starter.sh
```

## Connector System

### Providers

`openai`, `anthropic`, `gemini`, `grok`, `google`, `meta`, `mistral`, `perplexity`, `xai`, `github`

### Jobs

- `memory_pull_prompt`
- `github_repo_sync`
- `custom_json_sync`

### Controls

- Create/update/delete connector
- `Run now`
- `Pause/Resume auto-sync`
- Auto-sync scheduler (24h default)

### Automatic Sync Note

For providers without direct memory APIs, Cortex supports a bridge-based automatic path:

- Set `bridge_url` (and optional `bridge_token`) in connector job config
- Scheduler can pull structured memory payloads automatically
- If not configured, prompt/paste fallback remains available

## Sharing and AI ID

- Policies: `full`, `professional`, `technical`, `minimal`
- Public profile cards: `/p/{handle}`
- QR generation for profile sharing
- API memory access: `GET /api/memory/{key}`

## Web App Areas

- `Add Data`
- `My Memory`
- `Share`
- `Connectors`
- `AI ID Card`

## CLI Quickstart

```bash
# Build graph from export
cortex extract <export-file> -o context.json

# Inspect
cortex stats context.json

# Run server + web app
cortex serve context.json --enable-webapp --port 8421
```

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

## API and Docs

- OpenAPI: `spec/openapi.json`
- Interactive docs: `/docs`
- Guides:
  - `docs/user-guide.md`
  - `docs/deployment.md`
  - `docs/security.md`
  - `docs/codebase-feature-guide.md`

## Launch Content Drafts

- Long-form X article: `docs/x-article-philosophy.md`
- Dev invitation post: `docs/x-post-dev-invite.md`
- Beta tester guide: `docs/beta-tester-guide.md`

## License

MIT
