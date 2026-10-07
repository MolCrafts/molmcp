# CLI reference

```
molmcp [-h] [-V] {serve,init,planes,route,config,harness,cache,gate,info,search,explore,index} ...
python -m molmcp …
```

The `molmcp` script is installed by `pip install molcrafts-molmcp`.
`python -m molmcp` is equivalent when the package is importable.

**Default with no arguments:** `molmcp planes` (list connectable planes).
`molmcp --version` / `-V` prints `molmcp <version>` from the installed
package metadata. `molmcp serve` with no plane id starts the composed stack.

## `molmcp serve [plane]`

With **no plane**, start the molcrafts core and FastMCP-mount every enabled
provider (`molvis_open`, `molq_list_jobs`, …). Pass a plane id for a
single-plane debug server (bare tool names).

```bash
molmcp serve
molmcp serve molvis
molmcp serve molq
```

| Argument / flag | Meaning |
|-----------------|---------|
| `plane` | Optional. Omit for the composed stack. `molcrafts` or a provider name for a focused process. `catalog` is not a plane, and neither is `harness` — see [Harness catalog](../concepts/harness.md). |
| `--disable PLANE` | Omit a provider mount (emitted by `molmcp init --disable`). |
| `--config PATH` | Explicit `molcrafts.json`. Not searched for in the working directory — scope comes from settings; see [`molmcp config`](#molmcp-config). |
| `--env LOCATOR` | Python env to discover packages from (venv root, interpreter, or site-packages). Overrides the `pythonEnv` setting. |
| `--transport {stdio,streamable-http}` | Override transport (default stdio / config). |
| `--host` / `--port` | HTTP bind (streamable-http only). Non-loopback needs `server.auth_token_env`. |
| `--no-discover` | Do not load `molmcp.providers` entry points (provider plane needs inject). |

On the composed server, core tools are `molcrafts__packages`; mounted
provider tools are `molcrafts__molvis_open`.

## `molmcp planes`

List the molcrafts core and optional provider planes.

```bash
molmcp planes
molmcp planes --json
```

## `molmcp route <task>`

Suggest which **provider** plane(s) to connect for a free-text task.
molcrafts is already the core connection.

```bash
molmcp route "draw dopamine"
molmcp route "list slurm jobs"
```

## `molmcp config`

Read and edit settings. Verb shape follows `claude config`.

```bash
molmcp config list                              # resolved settings + which files contributed
molmcp config get sources.molpy
molmcp config set sources.molpy pkg:molpy
molmcp config add excludes vendor               # list-valued keys
molmcp config remove sources.molpy
molmcp config harness set MolCrafts/harness --alias official
molmcp config harness set /srv/harness-checkout --alias mine
molmcp config harness remove --name official
```

| Flag | Meaning |
|------|---------|
| *(none)* | Write `~/.molmcp/settings.json` — the default, because a plane server inherits its working directory from the client that launched it |
| `--project` | Write `./.molmcp/settings.json` (checked in) |
| `--local` | Write `./.molmcp/settings.local.json` (untracked) |

Layers merge user → project → local. Unknown keys are an error rather than a
silent no-op. See the [installation guide](../get-started/installation.md#settings)
for every key.

`harness` holds entry objects rather than strings, so `set` and `add` refuse it
and the two `config harness` subcommands author it instead: `set` upserts the
entry named by `--name`, appending an unknown name last, and `remove` drops it.
Both take the scope flags above. `--owner`, `--repo` and `--ref` are optional,
so an entry can be written a coordinate at a time; whether one is complete
enough to serve from is decided at serve time rather than here — see
[Harness catalog](../concepts/harness.md).

`--path` is the other way to spell an origin: a checkout already on disk,
instead of those three coordinates. The two shapes are mutually exclusive, and
the settings type refuses an entry carrying both — a source naming two origins
has no answer to where it comes from.

There are **no environment variables**. The two the code still reads are
secrets, not configuration: the bearer token an HTTP-transport server checks
against, and `GITHUB_TOKEN` for `github:` sources. Both name a variable in
config rather than storing its value, which is the point — a settings file
is the wrong place for a credential.

## `molmcp harness`

Fetch and activate the harness sources this install names. Two subcommands,
`sync` and `rollback`, and they move one pointer in the two directions. `sync`
is the verb between a *configured* source and a served one: `molmcp config
harness set` writes a source's origin and `molmcp serve` reads an activation
pointer, with nothing fetching, publishing or activating in between until this
runs. `rollback` is the way back from a sync that turned out worse.

```bash
molmcp harness sync official
molmcp harness rollback official
```

`sync` resolves the named source's ref to a commit, publishes that commit into
the shared store under `<cache>/harness`, and promotes it in that source's own
pointer at `<cache>/harness.<name>.pointer` — `<cache>` being the directory the
`cacheDir` setting names. It prints the source, the resolved SHA and either
`activated` or `already activated`, then the published tree and the pointer
file. What a source, a store and a pointer are is
[Harness catalog](../concepts/harness.md).

`rollback` promotes that source's `previous` SHA back to `active`. It fetches
nothing and publishes nothing — the commit it activates is already in the store
— so it prints only the source, the restored SHA and the pointer file.

**It goes back one level; it is not a toggle.** Restoring `previous` clears it,
so after `sync A`, `sync B`, `rollback` the pointer holds `current = A` and no
`previous`, and a *second* `rollback` is refused exactly as a never-synced
source is. Returning to the newer commit means syncing again — `molmcp harness
sync official` — which re-downloads nothing, because a rollback prunes nothing
and B's tree is still published.

| Argument / flag | Meaning |
|-----------------|---------|
| `name` | Required, positional. The source to sync or roll back, spelled as the `harness` settings list names it. No default: with several sources configured, guessing one would fetch code, or change what a plane serves, without being asked. |
| `--config PATH` | Explicit `molcrafts.json`. Same flag as `molmcp serve`, and it can move the cache root the store and the pointer land under. |

Two syncs of one commit are one sync. The second reports `already activated`
and leaves the pointer untouched, `previous` included — that field holds the
SHA a rollback returns to, and re-activating the commit that is already current
would overwrite it with the SHA already in `current`. A *new* commit does move
the pointer, and the SHA it displaces becomes `previous`; both trees stay in
the store, so the previous harness and the current one can both be read.

What is published is a commit, never your working tree. A local source is read
through `git archive` at the resolved SHA, so an uncommitted file in the
checkout does not reach the published tree — which is what makes a local source
rollbackable and comparable against another commit, rather than whatever
happens to be on disk right now.

The transport follows the source's shape and not a flag: a source with a `path`
is read with a local git transport, one with `--owner`/`--repo`/`--ref` over
HTTPS. There is no `--local`, because the entry already names exactly one
origin and a flag would be a second answer to that question.

## `molmcp init <host>`

Install managed skills (user-level, overwritten) and the MCP JSON for one
host. Host is required: `grok`, `claude`, `cursor`, `codex`. Skills:

- `molcrafts` — API discovery constitution (always loaded)
- `molexp-plan` — interactive experiment planner (`/molexp-plan`)

```bash
molmcp init grok
molmcp init grok --disable molq
molmcp init claude -o ~/.claude.json
```

JSON is one `molcrafts` entry running `molmcp serve`, with `--disable` flags
for omitted mounts. `--disable molcrafts` errors. The command uses the
resolved absolute path to `molmcp`.

## `molmcp cache`

Report the shared code index, and reclaim it.

```bash
molmcp cache                # size, live bytes, entry count
molmcp cache --prune        # drop payloads past retention and over the ceiling
molmcp cache --gc           # drop snapshots for sources no longer configured
molmcp cache --vacuum       # hand freed pages back to the filesystem
```

`used_bytes` is live content; `size_bytes` is the file. They diverge after a
prune because SQLite reuses freed pages rather than shrinking, and only
`--vacuum` closes the gap — with no plane server running, since it needs
exclusive access. A blocked vacuum reports `skipped` and changes nothing.

## Offline knowledge helpers

These drive the collection index without an MCP client (they need at least one
configured source — see `molmcp config`):

| Command | Role |
|---------|------|
| `molmcp info` | Registry + index coverage |
| `molmcp search <query>` | Full collection search (`--kind`, `--namespace`, `--source`, `--limit`) |
| `molmcp explore <task>` | Bounded task context pack (`--budget-chars`, …) |
| `molmcp index` | Index configured sources (`--force`, optional source list) |

```bash
molmcp search "Conformer" --source molpy
molmcp index --force
```

## Client wiring

```bash
claude mcp add molcrafts -- molmcp serve
```

Or generate the composed map and managed skills with `molmcp init grok`.

See [Deploy](../get-started/deploy.md) for the full layout.

## Read next

- [Architecture](../concepts/architecture.md)
- [API reference](api.md)
- [Quickstart](../get-started/quickstart.md)
