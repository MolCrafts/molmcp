# Providers

A **Provider** is the unit of MCP functionality a package contributes when the discovery engine cannot answer a question on its own — a stateful runtime query (a local DB, an on-disk workspace), a capability that lives in a native extension or external tool that source discovery can't read, or a small execution shim. The package ships a Provider class plus an entry point; molmcp discovers them at startup and mounts them onto a single server.

> **Read [provider-design.md](provider-design.md) first.** That doc defines the four-condition rule that every tool must satisfy before earning a slot. Most ideas for new tools fail one of the four — the answer is usually "let the agent introspect and script it" instead of adding a tool.

## The contract

```python
from typing import Protocol
from fastmcp import FastMCP

class Provider(Protocol):
    name: str
    def register(self, mcp: FastMCP) -> None: ...
```

That's the whole interface. Two requirements:

1. A class-level `name` attribute — used as the [mount prefix](#namespacing) and the dedup key. Use the MolCrafts package name (`molpy`, `molpack`, ...).
2. A `register(mcp)` method — called once at server-build time. The Provider attaches tools, resources, and prompts to `mcp`.

molmcp uses `typing.Protocol` with `@runtime_checkable`, so you do **not** need to inherit from `Provider` — any class with a matching shape qualifies.

## Two ways to register a Provider

### 1. Explicit injection

The host calls `create_server(...)` and passes Provider instances directly:

```python
from molmcp import create_server
from molpack_mcp import MolpackProvider

server = create_server(
    "molcrafts",
    providers=[MolpackProvider()],
    discover_entry_points=False,
)
```

### 2. Entry-point auto-discovery

The MolCrafts package declares its Provider in `pyproject.toml`:

```toml
[project.entry-points."molmcp.providers"]
molpack = "molpack_mcp:MolpackProvider"
```

When you run `molmcp serve <name>` (without `--no-discover`), molmcp loads the
matching `molmcp.providers` entry point and serves **only that provider** as
the plane. Multi-provider mega-servers are removed — one process, one product.

## Namespacing

The MCP **server name is the plane / provider `name`**. Tools register with
bare names (`list_jobs`, `open`, …). Clients see `molq__list_jobs`. Different
products never share a tool namespace because they never share a process.

`provider.name` must match the plane id you serve (`molmcp serve molq` loads
the provider whose `name == "molq"`).

## Annotation requirement

Every tool a Provider registers **must** declare either `readOnlyHint` or `destructiveHint` via `ToolAnnotations`:

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_atom_count(filename: str) -> int:
    """Count atoms in a structure file."""
    ...

@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def write_pdb(structure: dict, path: str) -> None:
    """Write structure to a PDB file (overwrites existing)."""
    ...
```

molmcp's [annotations validator](middleware.md#annotations-validator) walks every registered tool at server build time and refuses to start the server if any tool is missing this. Why so strict? MCP clients use these hints to decide whether to auto-approve a tool call — without them, the user gets prompted for every call (annoying) or the tool gets auto-approved (dangerous). Either choice degrades the UX for the whole MolCrafts ecosystem.

You can disable the check with `validate_annotations=False`, but don't.

## Discovery hygiene

Auto-discovery is a security boundary: any package the user has installed *and* that declares the entry point can register itself. molmcp:

- Logs every discovered Provider at startup so the user can see what's loaded.
- Skips Providers that fail to instantiate, with a warning instead of crashing.
- Skips Providers whose loaded class doesn't satisfy the `Provider` protocol.
- Honors `--no-discover` on the CLI to bypass discovery entirely.

For locked-down environments, prefer explicit `providers=[...]` injection.

## First-party providers

molmcp ships five Providers in-tree, each registered through the
`molmcp.providers` entry point and each justified against the
four-condition rule — because it answers something the discovery engine
cannot: local runtime state, a native extension source discovery can't
read, or an external DSL:

| Provider class | Name | Reason it exists |
|----------------|------|-----|
| `MolqProvider` | `molq` | Reads `~/.molq/jobs.db` runtime state. |
| `MolexpProvider` | `molexp` | Reads a workspace catalog rooted at `workspace.json`; also serves the frozen layout contract + a read-only linter. |
| `LammpsProvider` | `lammps` | Doc navigator over docs.lammps.org — LAMMPS is a C++ binary with a DSL that source discovery cannot reach. Pure functions; no upstream dep. |
| `MolpyProvider` | `molpy` | Runtime catalog of `molpy.compute` / `molpy.io` classes plus a structure-file reader executor — walked from the live module at call-time, not hardcoded. |
| `MolpackProvider` | `molpack` | Runtime restraint catalog + `.inp` script inspector over `molpack.load_script`, plus a table mirroring molpack's Rust-side I/O formats. |

`molrs` also has a `MolrsProvider` in the source tree, but it is **not**
wired into the `molmcp.providers` entry points, so by default molrs
capabilities are reached through the built-in `DiscoveryProvider`, which
indexes the installed MolCrafts packages into a code graph — see
[provider-design.md](provider-design.md) for the philosophy and
[discovery.md](discovery.md) for the engine.

Third parties writing their own MCP plugins should still use the
`molmcp.providers` entry-point group; the same four-condition rule
applies — providers that re-export an upstream API as MCP tools will be
flagged in review.

## Read next

- **[Provider design](provider-design.md)** — the four-condition rule and what *not* to ship.
- **[Middleware](middleware.md)** — what wraps your Provider's tools.
- **[Write a Provider](../guides/write-a-provider.md)** — step-by-step tutorial.
