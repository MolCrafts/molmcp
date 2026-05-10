# Architecture

molmcp is the central piece of MCP infrastructure for the MolCrafts ecosystem. The default loop is **introspection-first**: agents read the upstream MolCrafts API through generic introspection tools and call it via Python or the package CLI. A Provider only joins the picture when there's a stateful query introspection cannot answer (see [Provider design](provider-design.md) for the four-condition rule).

```
                ┌────────────────────────────────────┐
                │  MCP clients                       │
                │  (Claude Code, Claude Desktop, …)  │
                └──────────────┬─────────────────────┘
                               │  stdio / streamable-http / sse
                               ▼
                ┌────────────────────────────────────┐
                │  molmcp                            │
                │  • IntrospectionProvider           │
                │  • Provider contract + discovery   │
                │  • PathSafety / ResponseLimit      │
                │  • Annotations validator           │
                │  • run_safe / fence_untrusted      │
                └──────────────┬─────────────────────┘
                               │
            ┌──────────────────┼──────────────────────┐
            ▼                  ▼                      ▼
      MolqProvider      MolexpProvider     third-party providers
      (jobs.db)         (workspace.json     (entry-point group
                         catalog)            molmcp.providers)
```

## Three responsibilities

### 1. Transport plumbing

molmcp delegates the wire-level work — JSON-RPC framing, transport adapters (stdio, streamable-http, sse), tool/resource/prompt decorators, the middleware pipeline — to its underlying server library. molmcp doesn't reinvent any of that, and you generally don't have to think about it: when you call `create_server(...)` you get a working server back.

### 2. Source introspection

`IntrospectionProvider` exposes seven read-only tools that work against any MolCrafts import root. This is the primary capability molmcp provides — most agent questions about a MolCrafts package are answered from its source via these tools, not from a pre-curated tool catalog.

### 3. The Provider contract (kept narrow)

Every other tool molmcp registers is a Provider tool, gated by `Provider` Protocol + `molmcp.providers` entry-point auto-discovery + the four-condition design rule. Two providers ship in-tree (`MolqProvider`, `MolexpProvider`); third-party packages plug in identically. Default safety middleware — path-traversal guards, response-size limits, startup-time annotation validation — is mounted automatically when `create_server(...)` is called.

## How a request flows through

```
Client   →   stdio        molmcp        mid-      mid-      Provider
                          decoder       ware 1    ware 2    tool

Claude   →   tools/call →  call_tool → Path-   → Response → @mcp.tool
calls                                   Safety   Limit       def get_source(...)
mcp__molpy
__get_source                                                ← returns text
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
- Multiple MolCrafts packages can be exposed via a single server with `mcp.mount(prefix=...)`. Agents see `molpy__list_modules` and `molpack__pack_box` side by side.
- Updating the underlying transport library is a one-line dep bump in molmcp, not a coordinated change across N packages.

## What molmcp deliberately does *not* do

- **No re-exported domain tools.** No structure I/O facade, no `compute_rdf`, no `parse_smiles`. Those are reachable through introspection plus a 3-line Python or CLI invocation — see [Provider design](provider-design.md) for why a tool catalog that mirrors upstream is a maintenance trap.
- **No batteries-included science deps at the foundation layer.** molmcp's wheel pulls in only its server-framework dependency. The first-party `MolqProvider` / `MolexpProvider` are *lazy facades* — importing the provider class never imports the upstream dep; the probe happens at `register()` time, and a missing dep produces a clear runtime warning rather than a startup crash.
- **No opinions about Provider internals.** A Provider can be 5 lines or 5,000 — molmcp only requires that it has a `name` and a `register(mcp)` method.
- **No MolCrafts package import from the foundation.** Outside the in-tree providers (which are explicit, lazy, and entry-point-gated like third-party providers), molmcp imports nothing from `molpy`, `molcfg`, etc. That keeps it adoptable on any cadence.

## Read next

- **[Providers](providers.md)** — the contract in detail
- **[Middleware](middleware.md)** — what each default middleware does and how to disable it
- **[Write a Provider](../guides/write-a-provider.md)** — practical guide
