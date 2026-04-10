[![PyPI](https://img.shields.io/pypi/v/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![Python](https://img.shields.io/pypi/pyversions/cortex-identity)](https://pypi.org/project/cortex-identity/)
[![License](https://img.shields.io/github/license/Junebugg1214/Cortex-AI)](https://github.com/Junebugg1214/Cortex-AI/blob/main/LICENSE)

# Cortex

Cortex is a local-first CLI that gives every AI tool the same Mind.

Use Cortex to:
- create one portable Mind with durable memory, policy, and mounts
- attach Brainpacks as specialist knowledge
- connect Manus, Hermes, Codex, Cursor, and Claude Code with first-class commands
- serve MCP, API, Manus bridge, and UI runtimes locally
- repair store and config drift safely with `cortex doctor --fix`

## Why Cortex Feels Unified Now

Cortex is no longer a pile of adjacent features.

It has one top-level object and one first-class CLI:

- **Mind**: your portable identity, memory, preferences, policy, and mounts
- **Brainpacks**: attachable specialist modules that compose into a Mind
- **Connect**: runtime wiring for Manus and local AI tools
- **Serve**: live MCP, API, Manus bridge, and UI surfaces
- **Doctor**: repair and hardening for the local Cortex workspace

Portable AI and Git for AI Memory still matter. They now fit underneath the same model:

- **Portable AI** is the ingest and sync path for a Mind
- **Git for AI Memory** is the advanced history, review, and governance layer

## Install

Recommended package install:

```bash
python3.11 -m pip install "cortex-identity[server]"
```

Source install from this repository:

```bash
git clone https://github.com/Junebugg1214/Cortex-AI.git
cd Cortex-AI
python3.11 -m pip install -e ".[server]"
```

Notes:
- Use `python3.11 -m pip`, not plain `pip`.
- Cortex supports Python 3.10+, but `python3.11` is the smoothest default for local setup.
- The `server` extra installs the local runtime surfaces used by `cortex serve`.

## Start Here

Five-minute first run:

```bash
mkdir cortex-workspace
cd cortex-workspace
cortex init
cortex mind remember self "I prefer concise, implementation-first answers."
cortex mind status self
cortex doctor
```

What this does:

| Command | What it does |
| --- | --- |
| `mkdir cortex-workspace && cd cortex-workspace` | Creates a clean workspace for your Cortex store. |
| `cortex init` | Creates `.cortex/config.toml`, generates reader and writer API keys, initializes the canonical store, creates the default Mind `self` if needed, and prints the next recommended commands. |
| `cortex mind remember self "..."` | Teaches the default Mind one durable fact or preference directly. |
| `cortex mind status self` | Shows the default Mind's manifest, branch, policy, attachments, and mounts. |
| `cortex doctor` | Checks the local workspace for store or config issues before they become runtime problems. |

## First-Class CLI

The default help surface is now intentionally small:

| Command | Use it when you want to... |
| --- | --- |
| `cortex init` | bootstrap a canonical `.cortex/` workspace and default Mind |
| `cortex mind ...` | create, inspect, compose, and mount Minds |
| `cortex pack ...` | build and manage Brainpacks |
| `cortex connect ...` | wire Cortex into Manus or local runtimes |
| `cortex serve ...` | run the live API, MCP, Manus bridge, or UI |
| `cortex doctor` | diagnose and safely repair local setup issues |

For the full advanced and compatibility surface, run:

```bash
cortex --help-all
```

That includes legacy and low-level commands such as `portable`, `remember`, `sync`, `build`, `audit`, `server`, `mcp`, `commit`, `branch`, `merge`, and `review`.

## Common Workflows

### 1. Create and Compose a Mind

```bash
cortex init
cortex mind remember self "I prefer concise, implementation-first answers."
cortex mind remember self "We are building Cortex as a first-class AI CLI."
cortex mind compose self --to codex --task "product strategy"
```

Use this flow when you want one portable Mind to carry across tools instead of restarting from zero in every runtime.

### 2. Add a Brainpack

```bash
cortex pack init ai-memory --description "Portable AI memory research"
cortex pack ingest ai-memory ~/notes/ai-memory ~/Downloads/papers --recurse
cortex pack compile ai-memory --suggest-questions
cortex mind attach-pack self ai-memory --always-on --target codex --task-term memory
```

Use Brainpacks when you want specialist knowledge to be compiled once and composed into the Mind only when relevant.

### 3. Connect Local Runtimes

Check before you install:

```bash
cortex connect hermes --check --project .
cortex connect codex --check --project .
cortex connect cursor --check --project .
cortex connect claude-code --check --project .
```

Install the Cortex MCP wiring:

```bash
cortex connect hermes --install --project .
cortex connect codex --install --project .
cortex connect cursor --install --project .
cortex connect claude-code --install --project .
```

Then materialize the actual Mind into those runtimes:

```bash
cortex mind mount self --to hermes codex cursor claude-code --task "support"
```

### 4. Connect Manus

Use `connect` to prepare the connector and `serve` to run the bridge:

```bash
cortex connect manus --check
cortex connect manus --url https://your-https-endpoint.example/mcp --write-config ./manus-mcp.json
cortex serve manus --config .cortex/config.toml --host 127.0.0.1 --port 8790
```

Notes:
- Manus expects an HTTPS MCP endpoint.
- `--print-config` now masks secrets by default; use `--write-config <path>` for a paste-ready file or `--reveal-secret` only when you explicitly want the live token printed.
- For local testing, use a tunnel such as ngrok in front of `cortex serve manus`.
- For persistent production use, host the bridge behind stable HTTPS.

### 5. Run Local Runtime Surfaces

```bash
cortex serve api --check
cortex serve mcp --check
cortex serve manus --check
cortex serve ui --open
```

What each surface is for:

| Command | Purpose |
| --- | --- |
| `cortex serve api` | Runs the local REST API server. |
| `cortex serve mcp` | Runs the local Cortex MCP server over stdio. |
| `cortex serve manus` | Runs the Manus-friendly hosted MCP bridge. |
| `cortex serve ui` | Launches the local Cortex infrastructure UI. |

## Production-Ready CLI Habits

If you want Cortex to stay reliable as it grows, these are the habits to keep:

| Command | Why it matters |
| --- | --- |
| `cortex doctor` | Catch workspace issues early. |
| `cortex doctor --fix` | Apply safe repairs to first-class store and config issues. |
| `cortex doctor --fix-store` | Normalize accidental root-level stores back into the canonical `.cortex/` layout. |
| `cortex connect <target> --check` | Validate runtime readiness before you install or mount. |
| `cortex serve <surface> --check` | Validate runtime wiring before you expose a live service. |
| `--format json` | Use machine-readable output in automation and CI. |

Important defaults:
- Cortex strongly prefers a canonical `.cortex/` store.
- `cortex init` is idempotent and safe to rerun.
- `cortex doctor --fix` is the supported path for recovering from common local misconfiguration.

## Compatibility and Legacy Commands

The new CLI is Mind-first, but backward compatibility still exists.

If you already use the older flows:
- `portable`, `remember`, and `sync --smart` still work
- if a default Mind is configured, those commands route through that Mind
- `server` and `mcp` still work as compatibility entrypoints
- `cortex-manus` still maps to the Manus bridge

The recommended path for new users is still:

```bash
cortex init
cortex mind ...
cortex pack ...
cortex connect ...
cortex serve ...
cortex doctor
```

## More Docs

- [docs/MINDS.md](docs/MINDS.md)
- [docs/BRAINPACKS.md](docs/BRAINPACKS.md)
- [docs/PORTABILITY.md](docs/PORTABILITY.md)
- [docs/MANUS_QUICKSTART.md](docs/MANUS_QUICKSTART.md)
- [docs/HERMES_QUICKSTART.md](docs/HERMES_QUICKSTART.md)
- [docs/AGENT_QUICKSTARTS.md](docs/AGENT_QUICKSTARTS.md)
- [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md)
- [docs/CLI_UNIFICATION_PRD.md](docs/CLI_UNIFICATION_PRD.md)
- [docs/CORTEX_MIND_PRD.md](docs/CORTEX_MIND_PRD.md)

## Contributing

If you are changing Cortex itself rather than just using it:

```bash
python3.11 -m pip install -e ".[dev,server]"
python3.11 -m pytest tests -q --tb=short
ruff check cortex tests
ruff format cortex tests
```

## Uninstall

Delete the workspace you initialized, including `.cortex/`, any exported `portable/` artifacts you no longer want, and any runtime config blocks that Cortex added under its managed markers.
