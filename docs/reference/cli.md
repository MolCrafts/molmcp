# CLI reference

```
molmcp [-h] {serve,planes,route,client,config,cache,info,search,explore,index} ...
python -m molmcp …
```

The `molmcp` script is installed by `pip install molcrafts-molmcp`.
`python -m molmcp` is equivalent when the package is importable.

**Default with no arguments:** `molmcp planes` (list connectable planes).
There is **no** bare `molmcp` that starts a mega-server.

## `molmcp serve <plane>`

Start **one** MCP plane (one process, one server name = plane id).

```bash
molmcp serve catalog
molmcp serve molcrafts
molmcp serve molvis
molmcp serve molq
```

| Argument / flag | Meaning |
|-----------------|---------|
| `plane` | Required. `catalog` \| `molcrafts` \| a provider name (`molvis`, `molq`, …). Run `molmcp planes`. |
| `--config PATH` | Explicit `molcrafts.json`. Not searched for in the working directory — scope comes from settings; see [`molmcp config`](#molmcp-config). |
| `--env LOCATOR` | Python env to discover packages from (venv root, interpreter, or site-packages). Overrides the `pythonEnv` setting. |
| `--transport {stdio,streamable-http}` | Override transport (default stdio / config). |
| `--host` / `--port` | HTTP bind (streamable-http only). Non-loopback needs `server.auth_token_env`. |
| `--no-discover` | Do not load `molmcp.providers` entry points (provider plane needs inject). |

Tool ids on the client are `<plane>__<tool>` (e.g. `molcrafts__packages`,
`molvis__open`).

## `molmcp planes`

List connectable product domains (on-demand multi-link catalog).

```bash
molmcp planes
molmcp planes --json
```

## `molmcp route <task>`

Suggest which plane(s) to connect for a free-text task.

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
```

| Flag | Meaning |
|------|---------|
| *(none)* | Write `~/.molmcp/settings.json` — the default, because a plane server inherits its working directory from the client that launched it |
| `--project` | Write `./.molmcp/settings.json` (checked in) |
| `--local` | Write `./.molmcp/settings.local.json` (untracked) |

Layers merge user → project → local. Unknown keys are an error rather than a
silent no-op. See the [installation guide](../get-started/installation.md#settings)
for every key.

There are **no environment variables**. The two the code still reads are
secrets, not configuration: the bearer token an HTTP-transport server checks
against, and `GITHUB_TOKEN` for `github:` sources. Both name a variable in
config rather than storing its value, which is the point — a settings file
is the wrong place for a credential.

## `molmcp client [host]`

Emit the standard `mcpServers` JSON. Every host reads this shape; the optional
host (`claude`, `cursor`, `grok`) only selects the default output path.

```bash
molmcp client                          # stdout, all planes
molmcp client --disable molq
molmcp client claude -o ~/.claude.json
```

A disabled plane is absent from the map. The command written is the resolved
absolute path to `molmcp`, since desktop hosts do not inherit a shell PATH.

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

## Client wiring (multi-link)

```bash
claude mcp add catalog -- molmcp serve catalog
claude mcp add molcrafts -- molmcp serve molcrafts
claude mcp add molvis -- molmcp serve molvis
```

Or generate the whole map at once with `molmcp client`.

See [Deploy](../get-started/deploy.md) for the full layout.

## Read next

- [Architecture](../concepts/architecture.md)
- [API reference](api.md)
- [Quickstart](../get-started/quickstart.md)
