# CLI reference

```
molmcp [OPTIONS]
python -m molmcp [OPTIONS]
```

Both forms are equivalent. The `molmcp` script is installed by `pip install molcrafts-molmcp` via `[project.scripts]`; `python -m molmcp` works whenever the package is importable.

The default invocation needs no flags:

```bash
python -m molmcp
```

molmcp auto-detects whichever of `{molpy, molpack, molrs, molq, molexp}` are
importable, registers introspection over them, and loads any auto-discovered
providers. The flags below are for *narrowing*, *extending*, or otherwise
deviating from that default.

## Options

### `--name NAME`

Server name advertised to MCP clients. Default: `molmcp`.

This becomes the prefix in client-side tool naming (e.g., Claude Code's `mcp__<name>__<tool>`). Override only when running multiple molmcp servers side-by-side and you need distinct prefixes:

```bash
python -m molmcp --name molcrafts-dev
```

### `--import-root PACKAGE`

Top-level Python package whose source the built-in `IntrospectionProvider` should expose. Repeatable.

If `--import-root` is omitted, molmcp auto-detects whichever of
`{molpy, molpack, molrs, molq, molexp}` are importable in the active
environment. With none of those installed, it falls back to introspecting
`molmcp` itself so the seven tools are always present.

Pass `--import-root` explicitly only when you want to:

- *Narrow* to a single package:
  ```bash
  python -m molmcp --import-root molpy
  ```
- *Extend* beyond the default set (e.g. add a non-MolCrafts package):
  ```bash
  python -m molmcp --import-root molpy --import-root rdkit
  ```

### `--no-discover`

Skip auto-discovery of Providers via the `molmcp.providers` entry point group. Use when you want only `IntrospectionProvider` and no third-party providers loaded:

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
python -m molmcp --import-root molpy
```

### HTTP transport on port 9000

```bash
python -m molmcp --transport streamable-http --host 0.0.0.0 --port 9000
```

### Locked-down: introspection only, no provider discovery

```bash
python -m molmcp --no-discover
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
