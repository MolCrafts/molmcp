# Architecture

molmcp is the central piece of MCP infrastructure for the MolCrafts ecosystem. The default loop is **discovery-first**: a graph-based [discovery engine](discovery.md) statically indexes a codebase and agents resolve capabilities by querying that graph — symbols, relationships, examples, tests — instead of guessing names. A Provider only joins the picture when there's a stateful query the discovery engine cannot answer (see [Provider design](provider-design.md) for the four-condition rule).

```
                ┌────────────────────────────────────┐
                │  MCP clients                       │
                │  (Claude Code, Claude Desktop, …)  │
                └──────────────┬─────────────────────┘
                               │  stdio / streamable-http / sse
                               ▼
                ┌────────────────────────────────────┐
                │  molmcp                            │
                │  • DiscoveryProvider (molmcp_*)     │
                │  • Discovery engine core           │
                │  • Provider contract + discovery   │
                │  • PathSafety / ResponseLimit      │
                │  • Annotations validator           │
                │  • run_safe / fence_untrusted      │
                └──────────────┬─────────────────────┘
                               │
            ┌──────────────────┴──────────────────────┐
            ▼                                          ▼
   in-tree providers (entry points)          third-party providers
   molq · molexp · lammps · molpy · molpack   (same entry-point group
   — job DB, workspace catalog, LAMMPS docs,    molmcp.providers)
     runtime capability catalogs
```

## Three responsibilities

### 1. Transport plumbing

molmcp delegates the wire-level work — JSON-RPC framing, transport adapters (stdio, streamable-http, sse), tool/resource/prompt decorators, the middleware pipeline — to its underlying server library. molmcp doesn't reinvent any of that, and you generally don't have to think about it: when you call `create_server(...)` you get a working server back.

### 2. Discovery engine

`DiscoveryProvider` exposes six read-only `molmcp_*` tools backed by a graph-based discovery engine. The engine statically indexes a codebase — a local path, an installed package, or a GitHub repository — into a snapshot-cached code graph of symbols, relationships, examples, and tests. This is the primary capability molmcp provides: most agent questions are answered by querying that graph, not from a pre-curated tool catalog. See [Discovery engine](discovery.md) for the full design.

### 3. The Provider contract (kept narrow)

Every other tool molmcp registers is a Provider tool, gated by `Provider` Protocol + `molmcp.providers` entry-point auto-discovery + the four-condition design rule. Five providers ship in-tree (`MolqProvider`, `MolexpProvider`, `LammpsProvider`, `MolpyProvider`, `MolpackProvider`); third-party packages plug in identically. Default safety middleware — path-traversal guards, response-size limits, startup-time annotation validation — is mounted automatically when `create_server(...)` is called.

## How a request flows through

```
Client   →   stdio        molmcp        mid-      mid-      tool
                          decoder       ware 1    ware 2

Claude   →   tools/call →  call_tool → Path-   → Response → @mcp.tool
calls                                   Safety   Limit       def molmcp_find_
mcp__molmcp                                                  capability(...)
__molmcp_find_capability                                    ← returns dict
                                      ← passes ← truncates ←
                                        OK        if too big

         ←  encoded JSON-RPC response
         ←  stdio
```

Every Provider tool flows through every middleware. Adding a Provider doesn't require it to understand the middleware contract — it just declares its tools, and molmcp wires them up.

## Why this split?

Without molmcp, every MolCrafts package would have to:

- Author its own MCP server (~200 lines of boilerplate per package).
- Maintain its own transport configuration.
- Decide independently what counts as a "safe" path argument.
- Decide independently when to truncate large responses.
- Decide independently whether tool annotations are required.

The result would be: fragmented quality, inconsistent UX across packages, security defaults set wherever someone happened to remember. With molmcp:

- A user runs **one** invocation pattern (`python -m molmcp ...`).
- Security defaults are uniform across every MolCrafts package.
- Multiple MolCrafts packages can be exposed via a single server with `mcp.mount(namespace=...)`. Agents see `molmcp_find_capability` and `molpack_pack_box` side by side.
- Updating the underlying transport library is a one-line dep bump in molmcp, not a coordinated change across N packages.

## What molmcp deliberately does *not* do

- **No re-exported domain tools.** No structure I/O facade, no `compute_rdf`, no `parse_smiles`. Those are discoverable through the discovery engine plus a 3-line Python or CLI invocation — see [Provider design](provider-design.md) for why a tool catalog that mirrors upstream is a maintenance trap.
- **No batteries-included science deps at the foundation layer.** molmcp's wheel pulls in only its server-framework dependency. First-party providers under `providers/` are lazy facades: importing the provider class does not import molq/molexp/…; the probe runs at `register()` time.
- **No opinions about Provider internals.** A Provider needs `name` and `register(mcp)` only.
- **No science-package imports outside providers.** Core layers never import molq/molpy/…; only in-tree providers do, lazily.

## Read next

- **[Providers](providers.md)** — the contract in detail
- **[Middleware](middleware.md)** — what each default middleware does and how to disable it
- **[Write a Provider](../guides/write-a-provider.md)** — practical guide
