# Quickstart

Stand up an MCP server that exposes the MolCrafts ecosystem to an agent, in 60 seconds.

## 1. Run the server

```bash
python -m molmcp
```

That's it — no flags needed. molmcp auto-detects whichever of
`{molpy, molpack, molrs, molq, molexp}` are importable in the active
environment and registers introspection over them. Auto-discovered providers
(`MolqProvider`, `MolexpProvider`, and any third-party `molmcp.providers`
entry point) load on top.

The server stays in the foreground, talking MCP over stdin/stdout. `Ctrl+C` to stop.

## 2. Connect from Claude Code

In another terminal:

```bash
claude mcp add molcrafts -- python -m molmcp
```

The `--` separates Claude Code's args from molmcp's; everything after `--` is the command Claude Code spawns each session.

After this, ask Claude:

> What modules does molpy expose? Show me the source of `molpy.core.atomistic.Atomistic`.

Behind the scenes Claude calls:

- `mcp__molcrafts__list_modules`
- `mcp__molcrafts__get_source`

The `mcp__<name>__<tool>` prefix tracks the name you registered with (`molcrafts` here).

For the full local-stdio walkthrough — verifying with `claude mcp list`, the in-tree `MolqProvider` / `MolexpProvider` tools, and per-client wiring — see [Deploy](deploy.md).

## 3. The seven introspection tools

| Tool | What it does |
|------|--------------|
| `list_modules(prefix=None)` | Walks the import tree and returns all module names. |
| `list_symbols(symbol)` | Lists public symbols of a module **or** members of a class (kind-tagged) with one-line summaries. |
| `get_source(symbol)` | Returns full source for a module / class / method. |
| `get_docstring(symbol)` | Returns the cleaned docstring. |
| `get_signature(symbol)` | Returns the call signature with type hints. |
| `read_file(relative_path, start, end)` | Reads a line range from any source file in the package. |
| `search_source(query, module_prefix, max_results)` | Case-insensitive substring search. |

Every tool is marked `readOnlyHint=True`, so MCP clients can auto-approve them safely.

## 4. Run over HTTP instead

For sharing the server across processes or machines:

```bash
python -m molmcp --transport streamable-http --host 127.0.0.1 --port 8787
```

## What's next?

- **[Expose a package](../guides/expose-a-package.md)** — deeper guide on the introspection tools
- **[Write a Provider](../guides/write-a-provider.md)** — add *domain* tools (build, pack, simulate) from your MolCrafts package
- **[Architecture](../concepts/architecture.md)** — how molmcp composes the pieces
