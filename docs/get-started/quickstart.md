# Quickstart

Stand up an MCP server that exposes the MolCrafts ecosystem to an agent, in 60 seconds.

## 1. Run the server

```bash
python -m molmcp
```

That's it — no flags needed. molmcp indexes the MolCrafts packages
`{molpy, molpack, molrs, molq, molexp, molnex}` for graph-based discovery
— from a local install when present, from GitHub otherwise. The in-tree
providers (`MolqProvider`, `MolexpProvider`, `LammpsProvider`,
`MolpyProvider`, `MolpackProvider`) and any third-party `molmcp.providers`
entry point load on top.

The server stays in the foreground, talking MCP over stdin/stdout. `Ctrl+C` to stop.

## 2. Connect from Claude Code

In another terminal:

```bash
claude mcp add molcrafts -- python -m molmcp
```

The `--` separates Claude Code's args from molmcp's; everything after `--` is the command Claude Code spawns each session.

After this, ask Claude:

> What does molpy provide for computing a radial distribution function? Show me `molpy.core.atomistic.Atomistic`.

Behind the scenes Claude calls:

- `mcp__molcrafts__molmcp_find_capability`
- `mcp__molcrafts__molmcp_describe_symbol`

The `mcp__<name>__<tool>` prefix tracks the name you registered with (`molcrafts` here).

For the full local-stdio walkthrough — verifying with `claude mcp list`, the in-tree provider tools, and per-client wiring — see [Deploy](deploy.md).

## 3. The six discovery tools

When discovery sources are configured, molmcp exposes six composable,
graph-backed tools (all read-only):

| Tool | What it does |
|------|--------------|
| `molmcp_find_capability(task, source=None, max_results=8)` | Primary tool — describe a task, get ranked symbol matches with signature, summary, examples, tests, and callers. |
| `molmcp_search_symbols(query, source=None, kind=None, max_results=30)` | Full-text search over indexed symbols by name, qualname, or summary. |
| `molmcp_describe_symbol(qualname, source=None, include_source=False)` | Full detail for one symbol, optionally with source code. |
| `molmcp_relations(qualname, relation, source=None, depth=1, max_results=40)` | Walk the graph from a symbol — `callers`, `callees`, `implementers`, `subclasses`, `implementations`, `references`, `examples`, `tests`, `impact`. |
| `molmcp_outline(source=None, path=None)` | Map a source's packages/modules to their symbols — the "where do I look" tool. |
| `molmcp_refresh(source=None)` | Force a fresh re-index of a source. |

Every tool is marked `readOnlyHint=True`, so MCP clients can auto-approve
them safely, and every response carries a `snapshot` block so the agent
knows which revision of the source it is looking at.

## 4. Run over HTTP instead

For sharing the server across processes or machines:

```bash
python -m molmcp --transport streamable-http --host 127.0.0.1 --port 8787
```

## What's next?

- **[Expose a package](../guides/expose-a-package.md)** — deeper guide on the discovery tools
- **[Discovery engine](../concepts/discovery.md)** — how the code graph is built and queried
- **[Write a Provider](../guides/write-a-provider.md)** — add *domain* tools (build, pack, simulate) from your MolCrafts package
- **[Architecture](../concepts/architecture.md)** — how molmcp composes the pieces
