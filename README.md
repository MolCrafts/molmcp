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

```bash
# Print Grok config.toml fragments — every plane enabled=true
molmcp client grok

# Drop what you do not want
molmcp client grok --disable molq --disable molexp

# Re-enable after a disable
molmcp client grok --disable molq --enable molq

# Claude-style JSON (enabled planes only)
molmcp client claude --disable molq
```

Paste into `~/.grok/config.toml` (or pipe to a file). Tool ids look like
`molvis__open`, not `molmcp__molvis_open`.

## CLI

```bash
uv sync --extra dev
uv run molmcp planes              # list planes
uv run molmcp client grok         # all planes on
uv run molmcp client grok --disable molq
uv run molmcp route "draw dopamine"
uv run molmcp serve catalog       # one plane per process
uv run molmcp serve molvis
uv run molmcp search "Conformer"  # offline index search
uv run molmcp index
```

## Config (`molcrafts.json`, schema_version `"2"`)

Used by the **molcrafts** knowledge plane (and optional HTTP auth). Provider
planes do not need a config file.

```json
{
  "schema_version": "2",
  "sources": {
    "workspace": ".",
    "molpy": "pkg:molpy"
  },
  "watch": true,
  "server": { "transport": "stdio" }
}
```

Schema v1 and the old `providers: [...]` mega-server field are **not** supported.

## Install

```bash
uv sync --extra dev
uv run pytest -v
```

## Design rules

1. **Multi-link on-demand** — one process = one plane = one MCP server name.
2. **Bare tool names** — plane id is the server name; tools are `open`, not `open`.
3. **No science tool mirror** — no `show_smiles` / `draw_dopamine`; discovery + Python.
4. **Providers** register via `molmcp.providers` entry points and are served with
   `molmcp serve <name>`.

## Documentation

Full manual: [docs.molcrafts.org/molmcp](https://docs.molcrafts.org/molmcp/)
(sources in [`docs/`](docs/)):

- [Architecture](https://docs.molcrafts.org/molmcp/concepts/architecture/)
- [Quickstart](https://docs.molcrafts.org/molmcp/get-started/quickstart/)
- [MolVis workbench](https://docs.molcrafts.org/molmcp/guides/molvis-workbench/)
- [CLI reference](https://docs.molcrafts.org/molmcp/reference/cli/)

Local sources: `docs/concepts/architecture.md`, `docs/guides/molvis-workbench.md`.
