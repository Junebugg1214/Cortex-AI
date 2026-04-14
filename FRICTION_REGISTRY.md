# Friction Registry

Specialist 1 audit of user-facing friction across the Cortex CLI, local UI, REST API, MCP server, onboarding flow, and core end-to-end workflows.

Items are numbered for downstream fixes and sorted by severity, with `CRITICAL` items first.

## 1. Unknown CLI input silently routes to `migrate`
Location  
`cortex/cli_entrypoint.py::_route_default_subcommand`, `cortex/cli_entrypoint.py::main`

What happens today  
If the first CLI token is not a known subcommand, Cortex rewrites the argv list to `migrate ...` instead of surfacing an unknown-command parse error.

Why it fails the user  
A typo, stale muscle memory, or copied command fragment can trigger a different operation than the user intended. That breaks the expected command-line safety boundary and makes mistakes hard to diagnose.

Severity  
`CRITICAL`

## 2. Main help hides large parts of the product surface
Location  
`cortex/cli_surface.py::CortexArgumentParser.format_help`, `cortex/cli.py`, `cortex/cli_entrypoint.py`

What happens today  
`cortex --help` shows only the first-class commands and pushes major workflows such as `sources`, `audience`, graph/versioning internals, and compatibility commands behind `--help-all`.

Why it fails the user  
The primary discovery surface hides important workflows unless the user already knows they exist. That increases time-to-first-success and makes common tasks feel “missing” rather than merely advanced.

Severity  
`HIGH`

## 3. Shell completion is static and shallow
Location  
`cortex/completion.py::_get_subcommands`, `cortex/completion.py::_get_flags`, `cortex/completion.py::generate_bash`, `cortex/completion.py::generate_zsh`, `cortex/completion.py::generate_fish`

What happens today  
Completion scripts are generated from argparse metadata only. They complete static flags and subcommands, but not runtime values.

Why it fails the user  
Users still have to memorize or manually look up Mind IDs, audience IDs, source IDs, refs, and similar dynamic values. That undercuts the value of completion precisely where Cortex gets most complex.

Severity  
`HIGH`

## 4. First-run onboarding is documentation-heavy instead of product-led
Location  
`cortex/cli_surface.py::HELP_TOPIC_TEXT["init"]`, `README.md`, `docs/PLATFORM_ONBOARDING.md`, `website/learn.html`

What happens today  
The first-use path is a help-and-docs bootstrap sequence. The product explains what to type, but it does not guide a user through setup in-product.

Why it fails the user  
A new user spends the first few minutes translating instructions into actions instead of completing a guided workflow. That raises dropout risk before Cortex demonstrates value.

Severity  
`HIGH`

## 5. Local UI opens as an operator dashboard, not a guided workspace
Location  
`cortex/webapp_shell_body.py`, `cortex/webapp_shell_js.py::loadWorkspace`, `loadMinds`, `loadMindView`, `previewMindCompose`, `withBusy`

What happens today  
The UI boots into a dense multi-tab control plane. Empty states are mostly descriptive text, and async actions usually only swap a button label such as “Refreshing...” or “Loading...”.

Why it fails the user  
New or partially configured users are not given one obvious next step, a first-run guided action, meaningful progress, or cancel/recovery affordances. The UI assumes operator context too early.

Severity  
`HIGH`

## 6. Error envelopes are inconsistent across REST and MCP
Location  
`cortex/server.py::_error_payload`, `cortex/server.py::dispatch_api_request`, `cortex/auth.py::authorize_api_key`, `cortex/mcp.py::_error_response`, `cortex/mcp.py::_tool_result`, `cortex/mcp.py::_handle_tools_call`

What happens today  
REST failures often return `{"status":"error","error":"..."}` bodies, auth failures are plain strings wrapped late, and MCP failures appear either as JSON-RPC errors or text-encoded tool payloads.

Why it fails the user  
Humans and integrators have to learn different failure shapes per surface. Recovery guidance is inconsistent, and scripting against errors is harder than it should be.

Severity  
`HIGH`

## 7. Conflict and review workflows are powerful but poorly guided
Location  
`cortex/cli_graph_version_commands.py::run_merge`, `cortex/cli_graph_version_commands.py::run_review`, `cortex/merge.py`, `cortex/review.py`, `cortex/cli_graph_commands.py::run_memory_resolve`, `run_memory_retract`, `run_claim_accept`, `run_claim_reject`, `run_claim_supersede`

What happens today  
Merge, review, and resolution flows depend on users knowing the right combination of modes and flags such as `--base`, `--incoming`, `--against`, `--mind`, `--choose`, `--dry-run`, `--conflicts`, `--resolve`, and `--abort`.

Why it fails the user  
Users can start the workflow incorrectly, get a terse missing-flag error, and still not know the next correct step. The system exposes capability but not a guided end-to-end path.

Severity  
`HIGH`

## 8. Source lineage and audience-policy surfaces are discoverable only after learning Cortex vocabulary
Location  
`cortex/cli_parser_portable.py`, `cortex/cli_mind_pack_commands.py::run_sources`, `cortex/cli_mind_pack_commands.py::run_audience`

What happens today  
Source lineage inspection/retraction and audience-policy compilation exist as secondary subcommands. Their outputs assume the user already understands stable source IDs, labels, templates, and audience compilation concepts.

Why it fails the user  
Core workflows like retracting a source or compiling for an audience require vocabulary the product does not teach at the moment the user needs it.

Severity  
`LOW`

## 9. Recurring compilation and sync flows are operator-centric
Location  
`cortex/agent/context_dispatcher.py::register_schedule`, `run_due_schedules`, `run_forever`, `cortex/sync/scheduler.py::start`, `_run_sync`, `cortex/cli_runtime_commands.py`

What happens today  
Recurring work is configured with cron expressions or interval timers, and the observable status is tuned more for operators than for task-oriented users.

Why it fails the user  
The common “run this again later” workflow requires technical scheduling knowledge and provides little visible reassurance after configuration.

Severity  
`LOW`

## 10. Brainpack mounting is split across too many surfaces
Location  
`cortex/cli_surface.py::CONNECT_HELP_EPILOG`, `cortex/webapp_shell_body.py` Minds and Brainpacks panels, `cortex/cli_mind_pack_commands.py::run_mind`, `run_pack`

What happens today  
Getting a Brainpack into a runtime spans `connect`, `pack`, `mind`, and runtime surfaces. Each step exists, but the workflow is not presented as one cohesive path.

Why it fails the user  
One of Cortex’s most important portability actions feels scattered and reconstructive. Users have to assemble the sequence themselves instead of following a guided mount workflow.

Severity  
`LOW`
