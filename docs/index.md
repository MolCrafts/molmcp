# molmcp

**The MCP foundation for the MolCrafts ecosystem.**

molmcp is the Model Context Protocol layer that MolCrafts packages share. Instead of every package — `molpy`, `molcfg`, `molexp`, `molpack`, `mollog`, `molq`, `molrec`, `molvis` — authoring its own MCP server, they all build on molmcp: same source-introspection tools, same security defaults, same Provider plugin contract. molmcp itself is pure infrastructure — it imports nothing from MolCrafts packages, so any of them can adopt it without dragging in the others.

The design contract is **introspection-first**: agents discover the MolCrafts API by reading source through generic introspection tools, then call it from Python or the package's CLI. molmcp adds a curated Provider only when the answer depends on runtime state introspection cannot see. See [Provider design](concepts/provider-design.md) for the four-condition rule that gates every tool.

## What molmcp gives the MolCrafts ecosystem

<div class="grid cards" markdown>

- :material-magnify: **Source introspection**

    Seven read-only tools — `list_modules`, `list_symbols`, `get_source`, `get_docstring`, `get_signature`, `read_file`, `search_source` — bound to any MolCrafts import root.

    [→ Quickstart](get-started/quickstart.md)

- :material-puzzle: **Provider plugin contract**

    A Provider may register a tool only when introspection cannot answer the question — typically a stateful query against a local DB or workspace. Two providers ship in-tree (`MolqProvider`, `MolexpProvider`); third-party packages plug in via the `molmcp.providers` entry-point group.

    [→ Provider design](concepts/provider-design.md)

- :material-shield-check: **Security defaults**

    `..` traversal blocked. Responses capped at 256 KB. Tools without `readOnlyHint`/`destructiveHint` refuse to start. `run_safe` for shelling out to Packmol / LAMMPS / AmberTools.

    [→ Security model](guides/security.md)

- :material-layers: **Composition without coupling**

    Auto-discovered Providers register through the `molmcp.providers` entry-point group; mount many in one server with `mcp.mount(prefix=...)`. molmcp itself depends on no MolCrafts package — they each adopt molmcp on their own schedule.

    [→ Architecture](concepts/architecture.md)

</div>

## A quick taste

```bash
pip install molcrafts-molmcp
python -m molmcp
```

That's enough — seven introspection tools online over MCP stdio against whichever of `{molpy, molpack, molrs, molq, molexp}` are installed in the active environment, plus the first-party `MolqProvider` / `MolexpProvider` tools when their packages are present. For the one-line `claude mcp add` recipe, multi-server setups, and per-client wiring, see [Deploy](get-started/deploy.md).

When a MolCrafts package has a stateful query that introspection genuinely cannot answer, it ships a Provider — see [Provider design](concepts/provider-design.md) for the rule and [Writing a Provider](guides/write-a-provider.md) for the mechanics.

## Why this exists

When LLM agents work on a MolCrafts project they need exact, current API knowledge — what's in `molpy.core.atomistic`, what `molpack.pack` accepts, what `molexp.Experiment` returns. Re-implementing source introspection per package is wasted work; the code is identical regardless of which MolCrafts package it points at. molmcp factors out the common layer, with security defaults that no one wants to maintain in N copies, so MolCrafts packages can focus on the *interesting* part: exposing the simulations, the parsers, the I/O — the things only they can do.

[Get started →](get-started/installation.md){ .md-button .md-button--primary }
[See the architecture →](concepts/architecture.md){ .md-button }
