# CLI reference

```
molmcp [OPTIONS]
molmcp serve [OPTIONS]
python -m molmcp [OPTIONS]
molmcp discovery <SUBCOMMAND> [OPTIONS]
```

The `molmcp` script is installed by `pip install molcrafts-molmcp` via `[project.scripts]`; `python -m molmcp` works whenever the package is importable.

`molmcp` (or `molmcp serve` / `python -m molmcp`) starts the MCP server. `molmcp discovery` drives the discovery engine directly, without an MCP client — see [`molmcp discovery`](#molmcp-discovery) below.

## `molmcp serve`

The default invocation needs no flags:

```bash
python -m molmcp
```

molmcp auto-detects whichever of `{molpy, molpack, molrs, molq, molexp}` are
importable, registers graph-based discovery over them, and loads any
auto-discovered providers. The flags below are for *narrowing*, *extending*,
or otherwise deviating from that default.

## Options

### `--name NAME`

Server name advertised to MCP clients. Default: `molmcp`.

This becomes the prefix in client-side tool naming (e.g., Claude Code's `mcp__<name>__<tool>`). Override only when running multiple molmcp servers side-by-side and you need distinct prefixes:

```bash
python -m molmcp --name molcrafts-dev
```

### `--source SPEC`

A discovery source the engine should index. Repeatable. A spec is one of:

- `path/to/repo` — a local directory.
- `pkg:<name>` — an installed Python package, resolved by import name.
- `github:owner/repo[@ref]` — a GitHub repository, downloaded at a
  resolved commit SHA (`GITHUB_TOKEN` is used when set).

If `--source` is omitted, molmcp defaults to whichever of
`{molpy, molpack, molrs, molq, molexp}` are importable in the active
environment, each as a `pkg:` spec.

Pass `--source` explicitly when you want to:

- *Narrow* to a single package:
  ```bash
  python -m molmcp --source pkg:molpy
  ```
- *Extend* the set (a local checkout, another package, a GitHub repo):
  ```bash
  python -m molmcp --source pkg:molpy --source /path/to/a/repo --source github:MolCrafts/molpack
  ```

### `--no-discover`

Skip auto-discovery of Providers via the `molmcp.providers` entry point group. Use when you want only the discovery tools and no third-party providers loaded:

```bash
python -m molmcp --no-discover
```

The first-party `MolqProvider` / `MolexpProvider` are entry-point-discovered too, so `--no-discover` skips them as well; pass them explicitly via `create_server(providers=[...])` from a custom host script if you need them under a locked-down setup.

### `--no-validate-annotations`

Skip the startup-time check that every registered tool has `readOnlyHint` or `destructiveHint`. Use only when prototyping a new Provider; never in production.

### `--transport {stdio,streamable-http,sse}`, `-t`

Transport protocol. Default: `stdio`.

- `stdio` — default. The server reads MCP messages from stdin and writes to stdout. Right for local clients (Claude Code, Claude Desktop) that spawn the server as a subprocess.
- `streamable-http` — HTTP with streaming. Right for sharing a server across processes or machines.
- `sse` — Server-Sent Events. Legacy; prefer `streamable-http` for new deployments.

### `--host ADDRESS`

Bind address for HTTP and SSE transports. Default: `127.0.0.1`. Ignored for `stdio`.

### `--port PORT`, `-p`

Port for HTTP and SSE transports. Default: `8787`. Ignored for `stdio`.

### `--help`, `-h`

Show usage and exit.

## Common invocations

### Default — every installed MolCrafts package

```bash
python -m molmcp
```

### Narrow to a single package

```bash
python -m molmcp --source pkg:molpy
```

### HTTP transport on port 9000

```bash
python -m molmcp --transport streamable-http --host 0.0.0.0 --port 9000
```

### Locked-down: discovery only, no provider discovery

```bash
python -m molmcp --no-discover
```

## `molmcp discovery`

Inspect and drive the discovery engine without an MCP client. Every
subcommand except `clean` takes a source spec (a local path,
`pkg:<name>`, or `github:owner/repo[@ref]`).

### `index SOURCE`

Index a source and print a summary — snapshot id, file/node/edge counts,
and the cache location.

```bash
molmcp discovery index pkg:molpy
```

### `verify SOURCE`

Index a source and run a self-check — file/node/edge counts, node- and
edge-kind breakdown, whether the FTS5 index is available, and a sample
search against a known symbol. Prints a health report and **exits
non-zero** if discovery is not working, so it is usable in CI or a
setup script.

```bash
molmcp discovery verify pkg:molpy
```

```
verifying discovery for: pkg:molpy
  snapshot:      local:hash:sha256-…
  origin:        local (freshness: fresh)
  files:         …
  nodes:         …  [field …, method …, function …, class …, module …]
  edges:         …  [contains …, calls …, imports …]
  unresolved:    …
  FTS5 index:    available
  sample search: 'RDF' -> ok
  result:        OK — discovery is working
```

### `query SOURCE TEXT [--kind KIND] [--limit N]`

Search indexed symbols in a source.

```bash
molmcp discovery query pkg:molpy "radial distribution function"
molmcp discovery query pkg:molpy reader --kind class --limit 10
```

`--kind` filters by node kind (e.g. `class`, `function`, `method`,
`test`); `--limit` caps the result count (default `20`).

### `outline SOURCE [--path PATH]`

Print a source's structure — packages/modules mapped to their symbols.
`--path` narrows to a file or subtree.

```bash
molmcp discovery outline pkg:molpy
molmcp discovery outline pkg:molpy --path molpy/compute
```

### `dump SOURCE [--output FILE]`

Dump a source's full code graph as JSON (nodes, edges, files,
unresolved references). Writes to `--output` if given, otherwise stdout.

```bash
molmcp discovery dump pkg:molpy --output graph.json
```

### `clean [--all]`

Prune old cached snapshots. With `--all`, remove the entire discovery
cache instead of pruning.

```bash
molmcp discovery clean
molmcp discovery clean --all
```

## Wiring into Claude Code

```bash
claude mcp add <name> -- python -m molmcp [molmcp options...]
```

Example:

```bash
claude mcp add molcrafts -- python -m molmcp
```

Note the `--` separator: everything after it is the molmcp invocation Claude Code will spawn each session. The `<name>` you give to `claude mcp add` is the prefix the agent sees on tools (`mcp__<name>__<tool>`); molmcp itself does not need `--name` unless you're running multiple servers.

## Wiring into Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "molcrafts": {
      "command": "python",
      "args": ["-m", "molmcp"]
    }
  }
}
```

Restart Claude Desktop for the server to appear in the tools picker.

## Read next

- **[API reference](api.md)** — programmatic `create_server` API
- **[Quickstart](../get-started/quickstart.md)** — walkthrough using these flags
