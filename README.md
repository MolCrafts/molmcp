# MolMCP

Multi-plane MCP for the MolCrafts ecosystem.

**Protocol:** MCP **2026-07-28** via **FastMCP 4.0.0b1** (+ MCP Python SDK v2).
Handshake-era clients still work — FastMCP 4 negotiates per connection.

Optional science packages (`molvis`, `molq`, `molexp`, …): if not installed,
that plane is **omitted from catalogs and client configs** (silent). Explicit
`molmcp serve <plane>` still errors with an install hint. This is runtime
behavior — not a test skip.

**One product domain per MCP connection** (separate process / server name).
There is no mega-server under `molmcp`. **Client default: all planes on.**
Turn planes off with `--disable` (and back on with `--enable`).

| Plane | Command | Role |
|-------|---------|------|
| `catalog` | `molmcp serve catalog` | Bootstrap: `list_planes`, `route(task)` |
| `molcrafts` | `molmcp serve molcrafts` | Knowledge pages (packages → outline → open) |
| `molvis` | `molmcp serve molvis` | Live viewer session (`open` / `exec` / `poll_events`) |
| `molq` | `molmcp serve molq` | Job store + opt-in submit/cancel |
| `molexp` | `molmcp serve molexp` | Workspace layout + scaffold |

Science APIs are **never** MCP tools. Discover them on the `molcrafts` plane,
then call them from agent Python or inside `molvis` `exec`.

## Client config (default: everything)

One standard `mcpServers` JSON, which every host reads — Claude Code and
Cursor natively, Grok alongside its own `config.toml`.

```bash
molmcp client                            # all planes, to stdout
molmcp client --disable molq --disable molexp
molmcp client --disable molq --enable molq   # re-enable after a disable
molmcp client claude -o ~/.claude.json
```

An optional host (`claude`, `cursor`, `grok`) picks the default output path;
the JSON itself is identical for all of them. A disabled plane is simply
absent from the map. Tool ids look like `molvis__open`, not
`molmcp__molvis_open`.

> In Grok, `~/.grok/config.toml` outranks the JSON sources. If an old molmcp
> entry lives there it still wins — `grok inspect` shows each server's origin.

## Configuration

Settings live in `~/.molmcp/settings.json`, edited through the CLI. There are
no environment variables.

```bash
molmcp config list                                # resolved settings + layers
molmcp config set sources.molpy pkg:molpy         # index a package
molmcp config set indexWorkspace true --project   # index this repo too
molmcp config add excludes vendor
molmcp config remove sources.molpy
```

A project may carry `.molmcp/settings.json` (checked in) and
`.molmcp/settings.local.json` (untracked); both layer over the user file.
Writes go to the user file unless `--project` / `--local` is passed, because a
plane server inherits its working directory from whichever client launched it.

**What gets indexed.** Auto-discovery finds installed MolCrafts distributions.
The working directory is *not* a source unless `indexWorkspace` says so — it
used to be, which meant an unconfigured install indexed whatever it happened
to be started next to.

| Key | Meaning |
|-----|---------|
| `sources` | Extra sources to index, `name → spec` (`pkg:`, `local:`, `github:`, path) |
| `indexWorkspace` | Index the working directory as well (default `false`) |
| `knowledgeScope` | Narrow which indexed sources the knowledge tools surface |
| `excludes` | Extra ignore globs for the file walk |
| `cacheDir`, `maxCacheBytes`, `maxCacheAgeDays` | Where the index lives and how big it may get |
| `pythonEnv` | Environment to auto-discover from (a venv root, python, or site-packages) |
| `discoverInclude`, `discoverExclude` | Force a distribution in or out of auto-discovery |
| `molexp.workspace`, `molq.database` | Provider-specific paths |

`molcrafts.json` is no longer picked up from the working directory; pass
`--config PATH` if you keep one.

## CLI

```bash
uv run molmcp planes              # list planes
uv run molmcp client              # client config, all planes on
uv run molmcp config list         # resolved settings
uv run molmcp route "draw dopamine"
uv run molmcp serve catalog       # one plane per process
uv run molmcp serve molvis
uv run molmcp search "Conformer"  # offline index search
uv run molmcp index
uv run molmcp cache               # index size; --prune / --gc / --vacuum to reclaim
```

## Install

```bash
uv sync --extra dev
uv run pytest -v
```

## Design rules

1. **Multi-link on-demand** — one process = one plane = one MCP server name.
2. **Bare tool names** — the plane id is the server name, so a tool registers
   as `open` and the client shows `molvis__open`.
3. **No science tool mirror** — no `show_smiles` / `draw_dopamine`; discovery + Python.
4. **Providers** register via `molmcp.providers` entry points and are served with
   `molmcp serve <name>`.
5. **No environment switches** — configuration is settings and CLI flags, so
   `molmcp config list` is the whole truth.

## Documentation

Full manual: [docs.molcrafts.org/molmcp](https://docs.molcrafts.org/molmcp/)
(sources in [`docs/`](docs/)):

- [Architecture](https://docs.molcrafts.org/molmcp/concepts/architecture/)
- [Quickstart](https://docs.molcrafts.org/molmcp/get-started/quickstart/)
- [MolVis workbench](https://docs.molcrafts.org/molmcp/guides/molvis-workbench/)
- [CLI reference](https://docs.molcrafts.org/molmcp/reference/cli/)

Local sources: `docs/concepts/architecture.md`, `docs/guides/molvis-workbench.md`.
