# Cortex

Own your AI memory and identity.

Cortex gives users one portable AI ID that can sync across assistants, with user-controlled storage:
- `Self-Host` on user infrastructure

No Local Vault mode in the consumer flow.

## What Changed (Current Product Direction)

- Connector-first UX: connect providers first, manual upload second
- Storage is now `Self-Host` only
- Consumer Mode hides technical controls by default
- Per-connector controls include `Run now` and `Pause/Resume auto-sync`
- Connector auto-sync worker runs every 24h
- Dashboard static/API issues fixed and shipping from `main`

## Core User Flow

1. Sign up / log in on `/app`
2. Use `Self-Host` mode (default and only mode)
3. Add connectors (OpenAI, Anthropic, Google, Meta, Mistral, Perplexity, xAI, GitHub)
4. Sync memory via connector jobs
5. Add manual files only when needed (fallback path)
6. Review memory graph / summary
7. Share selected memory via policies/formats/API keys/profile card

## One-Command Self-Host Starter

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git && cd Cortex-AI && CORTEX_REF=ae5b9d0b57e00aa27ac8d46bd635e9325934ca97 bash deploy/self-host-starter.sh
```

Then:
1. Run on your machine or VPS
2. Open your own `/app` URL
3. Create your account and continue onboarding there

To install from a private/authenticated repo URL:

```bash
CORTEX_REPO_URL=git@github.com:Junebugg1214/Cortex-AI.git CORTEX_REF=<tag-or-commit> bash deploy/self-host-starter.sh
```

## Web App

- `/app` tabs:
  - `Add Data` / `Import (Manual)` (consumer vs technical label)
  - `My Memory`
  - `Share`
  - `Connectors`
  - `AI ID Card`
- Multi-user signup/login supported
- Consumer Mode supported
- Onboarding progress HUD supported

## Storage Mode

### Self-Host

- Consumer flow disables manual upload on hosted instance and directs user to run their own Cortex server
- Intended ownership model: user runs server and keeps control of infra/data

## Connector System

- Providers:
  - `openai`, `anthropic`, `google`, `meta`, `mistral`, `perplexity`, `xai`, `github`
- Jobs:
  - `memory_pull_prompt`
  - `github_repo_sync`
  - `custom_json_sync`
- Controls:
  - create/update/delete
  - run now
  - pause/resume auto-sync
- Scheduler:
  - background auto-sync worker
  - 24h interval per connector metadata default

## Share and AI ID

- Disclosure policies:
  - `full`, `professional`, `technical`, `minimal`
- Export/share targets:
  - Claude XML
  - system prompt
  - markdown/docs-style
  - JSON resume format for ATS flow
- API key memory endpoint:
  - `GET /api/memory/{key}`
- Public profile cards:
  - `/p/{handle}`
  - QR generation supported

## Dashboard

- `/dashboard` pages:
  - Overview
  - Graph
  - Grants
  - Versions
  - Health
  - Settings
- Auth:
  - dashboard session cookie
  - optional explicit password via `CORTEX_DASHBOARD_PASSWORD`

## Install (Package)

```bash
pip install cortex-identity
```

Optional extras:

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

# Run server + web app
cortex serve context.json --enable-webapp --port 8421
```

## API / Docs

- OpenAPI: `spec/openapi.json`
- Interactive docs: `/docs`
- Main guides:
  - `docs/user-guide.md`
  - `docs/deployment.md`
  - `docs/security.md`
  - `docs/codebase-feature-guide.md`

## Repo Media

Regenerated assets are in:
- `assets/cortexai_x_45s.mp4`
- `assets/cortexai_webapp_x_45s.mp4`
- `assets/demo-own.mp4`, `assets/demo-own.gif`
- `assets/demo-share.mp4`, `assets/demo-share.gif`
- `assets/demo-api.mp4`, `assets/demo-api.gif`

Tape sources:
- `assets/demo-own.tape`
- `assets/demo-share.tape`
- `assets/demo-api.tape`

## License

MIT
