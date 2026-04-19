# Cortex CLI v2 design

This document is the migration contract for collapsing the Cortex CLI front door from a broad flat surface into two tiers:

- Tier 1: about 12 top-level verbs for the workflows most users run daily.
- Tier 2: namespaced verbs for administration, debugging, and advanced workflows.

This is a design-only document. It does not change parser behavior yet.

## Goals

- Keep the common path short: initialize, remember, mount, sync, compose, inspect status, and use Git-like versioning verbs.
- Move specialized workflows into clear namespaces instead of exposing every feature as a top-level command.
- Preserve discoverability with compatibility shims for one minor release.
- Make migrations explicit enough that docs, shell completions, and CI examples can be updated mechanically.

## Release policy

The current project line is `1.4.x`. CLI v2 should roll out as follows:

- `1.5.0`: introduce CLI v2 commands and keep compatibility shims for moved, aliased, and retired top-level commands.
- `1.5.x`: shims emit a one-line deprecation warning with the replacement command.
- `1.6.0`: remove retired and moved top-level shims unless the row below is marked `kept`.

`deprecation_release` and `removal_release` in the migration table use this policy. `n/a` means the command remains supported at that path.

## Tier 1: top-level verbs

These are the recommended front-door verbs for 95% of users:

```text
init
remember
mount
sync
compose
status
commit
branch
merge
log
diff
verify
```

Notes:

- `compose` is new as a top-level convenience for rendering context without writing a mount target.
- `mount` remains top-level for persistent target writes and watch-mode workflows.
- `sync` remains top-level for smart propagation across configured tools.
- `commit`, `branch`, `merge`, `log`, `diff`, and `verify` preserve the Git-for-memory mental model.

## Tier 2: namespaces

The recommended v2 namespace set is:

```text
mind
pack
source
audience
remote
governance
extract
serve
admin
debug
```

This is 10 namespaces because `governance` stays user-facing policy rather than being hidden under `admin`. If a strict 9-namespace cap is required later, fold `governance` into `admin governance` without changing the rest of this design.

### `cortex mind ...`

Canonical subcommands:

```text
init
list
switch
compose
mount
remember
attach
detach
status
ingest
mounts
```

Migration notes:

- `mind default` becomes `mind switch`.
- `mind attach-pack` becomes `mind attach`.
- `mind detach-pack` becomes `mind detach`.

### `cortex pack ...`

Canonical subcommands:

```text
init
list
ingest
compile
mount
publish
query
status
context
ask
lint
inspect
```

Migration notes:

- `pack export` becomes `pack publish`.
- `pack import` becomes `pack ingest --bundle`.
- `build` becomes `pack compile`.

### `cortex source ...`

Canonical subcommands:

```text
ingest
list
retract
status
```

Migration notes:

- The existing `sources` namespace is renamed to singular `source`.
- `scan` becomes `source status`.
- Platform pull/import flows become `source ingest` with explicit input format flags.

### `cortex audience ...`

Canonical subcommands:

```text
list
add
apply-template
show
preview
compile
log
```

Migration notes:

- `audience show` is the canonical read command.
- Existing `preview`, `compile`, and `log` remain nested advanced commands.

### `cortex remote ...`

Canonical subcommands:

```text
add
list
push
pull
fork
verify
remove
```

Migration notes:

- `connect` becomes an alias for `remote add`.
- `remote verify` is the new explicit check command for remote store reachability and trust metadata.

### `cortex governance ...`

Canonical subcommands:

```text
list
add
remove
show
check
```

Migration notes:

- `allow` and `deny` are folded into `governance add --effect allow|deny`.
- `delete` becomes `remove`.
- `show` is the canonical read command for a single rule.

### `cortex extract ...`

Canonical subcommands:

```text
run
status
coding
eval
refresh-cache
review
ab
benchmark
trace
```

Migration notes:

- `extract`, `ingest`, and `extract-coding` become `extract run` variants.
- Harness commands live under `extract`: `eval`, `refresh-cache`, `review`, `ab`, `benchmark`, and `trace`.
- `extract status` is reserved for extraction backend/config diagnostics.

### `cortex serve ...`

Canonical subcommands:

```text
api
mcp
ui
```

Migration notes:

- `server` becomes `serve api`.
- `mcp` becomes `serve mcp`.
- `ui` becomes `serve ui`.
- The current top-level `serve` namespace remains the canonical runtime namespace.

### `cortex admin ...`

Canonical subcommands:

```text
doctor
integrity
rehash
backup
restore
rotate
completion
openapi
benchmark
release-notes
migrate
identity
agent
```

Migration notes:

- Operational commands move here.
- `integrity rehash` becomes `admin rehash`.
- `backup export|verify|restore` becomes `admin backup ...`.
- `agent ...` moves here because it operates background monitors, schedules, and dispatch.

### `cortex debug ...`

Canonical subcommands:

```text
viz
timeline
digest
gaps
watch
query
blame
history
claims
contradictions
drift
review
stats
```

Migration notes:

- Reporting and exploratory graph-inspection commands move here.
- `watch` becomes debug-only unless it is specifically the mount watcher, which remains `mount watch`.

## Alias and retirement rules

- `alias`: the old command should continue to work for one minor release and print the exact new command.
- `nested`: the old top-level command is moved under a namespace and should warn for one minor release.
- `retired`: the old command name should not appear in v2 help. A shim may remain for one minor release if the command has active users or examples.
- `kept`: the command remains supported at the same path.
- `promoted`: the command becomes part of Tier 1 or a clearer primary path.

## Migration table

| old | new | status | deprecation_release | removal_release | migration note |
| --- | --- | --- | --- | --- | --- |
| `init` | `init` | kept | n/a | n/a | Keep as Tier 1 project/store initialization. |
| `connect` | `remote add` | alias | 1.5.0 | 1.6.0 | Alias to `cortex remote add`; keep shim for one minor release. |
| `serve` | `serve {api,mcp,ui}` | kept | n/a | n/a | Keep as the canonical runtime namespace. |
| `extract` | `extract run` | nested | 1.5.0 | 1.6.0 | Move extraction execution under `extract run`; shim kept for one minor release. |
| `extract-eval` | `extract eval` | nested | 1.5.0 | 1.6.0 | Extraction eval corpus runs live under the extraction harness namespace. |
| `extract-refresh-cache` | `extract refresh-cache` | nested | 1.5.0 | 1.6.0 | Replay-cache refresh moves under the extraction harness namespace. |
| `extract-review` | `extract review` | nested | 1.5.0 | 1.6.0 | Eval failure review moves under the extraction harness namespace. |
| `extract-ab` | `extract ab` | nested | 1.5.0 | 1.6.0 | Prompt A/B runs move under the extraction harness namespace. |
| `ingest` | `extract run --source ...` | nested | 1.5.0 | 1.6.0 | Normalize source ingestion through the extraction namespace; shim kept for one minor release. |
| `import` | `sync --to <target>` | retired | 1.5.0 | 1.6.0 | Replace platform-format import/export wording with explicit `sync`; shim kept for one minor release. |
| `memory` | `remember`, `source retract`, or `debug query` | retired | 1.5.0 | 1.6.0 | Split broad memory editing into task-specific commands; shim should route subcommands for one minor release. |
| `migrate` | `admin migrate` | nested | 1.5.0 | 1.6.0 | Move migration tooling under admin; shim kept for one minor release. |
| `query` | `debug query` | nested | 1.5.0 | 1.6.0 | Querying remains available but moves out of the front door. |
| `stats` | `debug stats` | nested | 1.5.0 | 1.6.0 | Statistics become a debug/reporting command. |
| `timeline` | `debug timeline` | nested | 1.5.0 | 1.6.0 | Timeline rendering becomes debug/reporting. |
| `contradictions` | `debug contradictions` | nested | 1.5.0 | 1.6.0 | Contradiction reports move under debug. |
| `drift` | `debug drift` | nested | 1.5.0 | 1.6.0 | Identity drift reports move under debug. |
| `diff` | `diff` | kept | n/a | n/a | Keep as Tier 1 version comparison. |
| `blame` | `debug blame` | nested | 1.5.0 | 1.6.0 | Provenance inspection moves under debug. |
| `history` | `debug history` | nested | 1.5.0 | 1.6.0 | Memory receipt history moves under debug. |
| `claim` | `debug claims` | nested | 1.5.0 | 1.6.0 | Claim ledger inspection/review moves under debug; shim kept for one minor release. |
| `checkout` | `checkout --at <ref>` | alias | 1.5.0 | 1.6.0 | Keep a hidden compatibility path while the rollback replacement lands; prefer explicit `--at`. |
| `rollback` | `checkout --at <ref>` | retired | 1.5.0 | 1.6.0 | Retire rollback wording; shim kept for one minor release. |
| `identity` | `admin identity` | nested | 1.5.0 | 1.6.0 | Identity init/show moves under admin. |
| `commit` | `commit` | kept | n/a | n/a | Keep as Tier 1 version creation. |
| `branch` | `branch` | kept | n/a | n/a | Keep as Tier 1 branch list/create command. |
| `switch` | `branch switch` | nested | 1.5.0 | 1.6.0 | Branch switching moves under the branch verb; shim kept for one minor release. |
| `merge` | `merge` | kept | n/a | n/a | Keep as Tier 1 merge command. |
| `review` | `debug review` | nested | 1.5.0 | 1.6.0 | Graph review/comparison becomes debug/reporting. |
| `log` | `log` | kept | n/a | n/a | Keep as Tier 1 history command. |
| `governance` | `governance {list,add,remove,show,check}` | kept | n/a | n/a | Keep as a policy namespace; rename nested verbs in CLI v2. |
| `remote` | `remote {add,list,push,pull,fork,verify,remove}` | kept | n/a | n/a | Keep as the sync/federation namespace. |
| `sync` | `sync` | kept | n/a | n/a | Keep as Tier 1 smart propagation. |
| `verify` | `verify` | kept | n/a | n/a | Keep as Tier 1 verification command. |
| `gaps` | `debug gaps` | nested | 1.5.0 | 1.6.0 | Gap analysis becomes debug/reporting. |
| `digest` | `debug digest` | nested | 1.5.0 | 1.6.0 | Digest generation becomes debug/reporting. |
| `viz` | `debug viz` | nested | 1.5.0 | 1.6.0 | Visualization becomes debug/reporting. |
| `watch` | `debug watch` or `mount watch` | nested | 1.5.0 | 1.6.0 | Generic export watching moves to debug; mount hot-refresh stays `mount watch`. |
| `sync-schedule` | `debug watch --sync` | retired | 1.5.0 | 1.6.0 | Collapse scheduler wording into the watch flow; shim kept for one minor release. |
| `extract-coding` | `extract run --kind coding` | nested | 1.5.0 | 1.6.0 | Coding-session extraction becomes an extraction mode. |
| `context-hook` | `mount hook` | nested | 1.5.0 | 1.6.0 | Hook installation/management belongs to mount workflows. |
| `context-export` | `compose --target <target> --stdout` | nested | 1.5.0 | 1.6.0 | Context rendering without writes becomes Tier 1 compose. |
| `context-write` | `mount <target>` | nested | 1.5.0 | 1.6.0 | Context file writes become Tier 1 mount. |
| `portable` | `sync`, `mount`, or `compose` | retired | 1.5.0 | 1.6.0 | Split the broad portability front door into explicit verbs; shim kept for one minor release. |
| `scan` | `source status` | retired | 1.5.0 | 1.6.0 | Replace scan with source status, per CLI consolidation proposal. |
| `remember` | `remember` | kept | n/a | n/a | Keep as Tier 1 fact/preference capture. |
| `status` | `status` | kept | n/a | n/a | Keep as Tier 1 health/status summary. |
| `mount` | `mount` | kept | n/a | n/a | Keep as Tier 1 persistent mount command. |
| `build` | `pack compile` | retired | 1.5.0 | 1.6.0 | Replace build with Brainpack compilation. |
| `audit` | `admin integrity` | retired | 1.5.0 | 1.6.0 | Replace broad audit wording with admin integrity. |
| `doctor` | `admin doctor` | nested | 1.5.0 | 1.6.0 | Move diagnostics under admin. |
| `integrity` | `admin integrity` or `admin rehash` | nested | 1.5.0 | 1.6.0 | Move integrity checks and rehash migration under admin. |
| `help` | `--help` | alias | 1.5.0 | 1.6.0 | Prefer standard parser help; keep `help` as a one-minor alias. |
| `mind` | `mind {init,list,switch,compose,mount,remember,attach,detach,status,ingest,mounts}` | kept | n/a | n/a | Keep as the Mind namespace and rename nested verbs. |
| `sources` | `source {ingest,list,retract,status}` | alias | 1.5.0 | 1.6.0 | Rename plural `sources` to singular `source`; shim kept for one minor release. |
| `audience` | `audience {list,add,apply-template,show,preview,compile,log}` | kept | n/a | n/a | Keep as the audience-policy namespace. |
| `ui` | `serve ui` | nested | 1.5.0 | 1.6.0 | Move UI serving under serve. |
| `pack` | `pack {init,ingest,compile,mount,publish,query,...}` | kept | n/a | n/a | Keep as the Brainpack namespace and rename nested verbs. |
| `benchmark` | `admin benchmark` | nested | 1.5.0 | 1.6.0 | Move self-host benchmarks under admin; extraction corpus throughput is `extract benchmark`. |
| `server` | `serve api` | nested | 1.5.0 | 1.6.0 | Replace server with explicit serve api. |
| `mcp` | `serve mcp` | nested | 1.5.0 | 1.6.0 | Replace top-level mcp with serve mcp. |
| `backup` | `admin backup` | nested | 1.5.0 | 1.6.0 | Move backup/export/restore under admin. |
| `agent` | `admin agent` | nested | 1.5.0 | 1.6.0 | Move monitor/dispatch/schedule operations under admin. |
| `openapi` | `admin openapi` | nested | 1.5.0 | 1.6.0 | Move contract generation under admin. |
| `release-notes` | `admin release-notes` | nested | 1.5.0 | 1.6.0 | Move release-note generation under admin. |
| `rotate` | `admin rotate` | nested | 1.5.0 | 1.6.0 | Move key rotation under admin. |
| `pull` | `source ingest --pull` | alias | 1.5.0 | 1.6.0 | Platform export pullback becomes source ingestion. |
| `completion` | `admin completion` | nested | 1.5.0 | 1.6.0 | Move shell completion generation under admin. |
| `-h` | `-h` | kept | n/a | n/a | Keep parser short-help behavior. |
| `--help` | `--help` | kept | n/a | n/a | Keep parser help behavior. |
| `--help-all` | `admin help --all` | alias | 1.5.0 | 1.6.0 | Keep one-minor alias for full command inventory. |

## Retired command replacement details

| retired old command | replacement invocation | shim kept for one minor version? |
| --- | --- | --- |
| `import` | `cortex sync --to <target>` | yes |
| `memory` | `cortex remember`, `cortex source retract`, or `cortex debug query` depending on subcommand | yes |
| `rollback` | `cortex checkout --at <ref>` | yes |
| `sync-schedule` | `cortex debug watch --sync` | yes |
| `portable` | `cortex sync`, `cortex mount`, or `cortex compose` depending on mode | yes |
| `scan` | `cortex source status` | yes |
| `build` | `cortex pack compile` | yes |
| `audit` | `cortex admin integrity` | yes |

## Implementation notes for the follow-up code PR

- Update `KNOWN_SUBCOMMANDS` only after the parser accepts the new namespace routes.
- Add shim handlers before removing old parser entries so existing scripts receive warnings instead of hard failures in `1.5.x`.
- Update shell completions and README examples in the same PR that changes parser behavior.
- Keep `cortex --help` focused on Tier 1 plus the Tier 2 namespaces.
- Move the full compatibility matrix behind `cortex admin help --all`.
- Add tests for every shim warning and for every replacement invocation in the migration table.
