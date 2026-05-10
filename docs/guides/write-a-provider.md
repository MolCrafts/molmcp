# Write a Provider

You're maintaining a MolCrafts package and you have a *stateful query* — something that depends on local runtime state (a DB, a workspace catalog, an OS-level config) that no amount of source introspection can recover. Read [Provider design](../concepts/provider-design.md) first; if your candidate tool fails any of the four conditions there, the right answer is usually to let the agent introspect upstream and write the script itself, not to ship a Provider tool.

If your tool *does* earn a slot, this guide walks through writing the Provider that ships with your package.

We'll use a hypothetical `molpack` workspace probe as the running example, building a Provider that exposes one tool: `list_pack_targets(workdir)`. The same pattern applies to any MolCrafts package whose runtime state lives outside its source.

## Step 1 — Make molmcp an optional dep of your package

In `molpack/pyproject.toml`:

```toml
[project.optional-dependencies]
mcp = ["molcrafts-molmcp >= 0.2, < 0.3"]
```

Don't make molmcp a hard dependency — users who don't need MCP shouldn't pull in the server framework.

## Step 2 — Decide where the Provider lives

The MolCrafts convention is a sibling package named `<pkg>_mcp`:

```
molpack/                 # the main package, no MCP knowledge
└── src/molpack/...

molpack_mcp/             # sibling package, the Provider
└── src/molpack_mcp/__init__.py
```

This keeps the MCP integration out of your main package's import graph. Users who don't run MCP never touch `molpack_mcp`.

For small packages it's fine to keep `molpack_mcp/` inside the same repo as a separate `[project.optional-dependencies]` install target, or as a second package in a workspace.

## Step 3 — Write the Provider class

Create `molpack_mcp/__init__.py`:

```python
"""MCP Provider for molpack."""
from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations


class MolpackProvider:
    name = "molpack"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def list_pack_targets(workdir: str) -> list[dict]:
            """List the in-progress pack targets cached under workdir.

            Reads the on-disk workspace catalog molpack maintains for an
            interactive packing session and returns one row per target —
            the kind of dashboard query the agent will want at the top
            of every session and that introspection over ``molpack``
            cannot answer because the answer depends on local files.

            Args:
                workdir: Workspace directory the user has been packing in.

            Returns:
                One dict per target with keys ``name``, ``status``,
                ``count``, ``last_updated``.
            """
            from molpack import workspace  # lazy import — keeps cold start fast
            return [t.to_dict() for t in workspace.scan(workdir).targets]
```

A few things worth calling out:

- **Earned its slot.** `list_pack_targets` reads runtime state (the on-disk catalog) — exactly the kind of question introspection over `molpack` source cannot answer. Stable signature, read-only, every-session frequency, single-shot answer: passes [the four conditions](../concepts/provider-design.md). A `pack_box(spec, workdir)` tool that *runs* the packing would fail condition 2 (mutating, file-writing) and belongs in upstream's API/CLI instead.
- **Class-level `name = "molpack"`.** This is both the dedup key and the recommended mount prefix.
- **`ToolAnnotations(readOnlyHint=True)`.** Required — molmcp will refuse to start the server otherwise. Use `destructiveHint=True` if your tool legitimately mutates external state (rare; most stateful-query tools are read-only by design).
- **Lazy import of the upstream module.** Don't `import molpack` at module top — when molmcp's auto-discovery instantiates your Provider, you want it cheap. Defer the import to the tool body so a missing or broken upstream dep produces a clean per-call error instead of crashing server startup. (For a production-grade pattern that turns the whole provider into a *lazy facade* — probing the dep at `register()` time and warning cleanly if it's absent — see how `MolqProvider` and `MolexpProvider` are wired in `src/molmcp/providers/`.)
- **Plain-dict return.** Don't return Pydantic models from tool functions; some MCP clients serialize them as JSON-strings instead of dicts. Stick to primitives, lists, dicts.

## Step 4 — Register the entry point

In `molpack_mcp/pyproject.toml` (or `molpack/pyproject.toml` if you ship them together):

```toml
[project.entry-points."molmcp.providers"]
molpack = "molpack_mcp:MolpackProvider"
```

The key (`molpack` here) is just a label — molmcp doesn't use it. The value is the dotted path to your Provider class.

## Step 5 — Test it

```python
# tests/test_mcp.py
import pytest
from molmcp import create_server


@pytest.fixture
def server():
    from molpack_mcp import MolpackProvider
    return create_server(
        "test",
        providers=[MolpackProvider()],
        discover_entry_points=False,  # skip entry-point lookup in tests
    )


async def test_list_pack_targets(server, tmp_path):
    # Seed a tiny workspace fixture under tmp_path here…
    result = await server.call_tool(
        "list_pack_targets",
        {"workdir": str(tmp_path)},
    )
    text = result.content[0].text
    assert "[" in text  # JSON array of target dicts
```

Run with `pytest tests/test_mcp.py -v`. molmcp's introspection tools are absent because we didn't pass `import_roots=["molpack"]` — only the Provider's tool is registered.

## Step 6 — Use it from an MCP client

The user installs your package and starts the server:

```bash
pip install molpack[mcp]
python -m molmcp
```

Auto-discovery finds the entry point, so `MolpackProvider` is registered. Because `molpack` is now an importable top-level package, it's also picked up by the default introspection roots. The agent now sees:

- The seven introspection tools (over every installed MolCrafts package, including `molpack`)
- `list_pack_targets` from your Provider

To wire into Claude Code:

```bash
claude mcp add molcrafts -- python -m molmcp
```

## Patterns worth knowing

### Mounting tools under your package name as a prefix

If your Provider registers more than one tool and you want them all prefixed (so they don't collide with other MolCrafts Providers in the same server), mount a sub-server:

```python
def register(self, parent_mcp):
    sub = FastMCP("molpack")

    @sub.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_pack_targets(workdir: str) -> list[dict]: ...

    @sub.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_pack_target(workdir: str, name: str) -> dict: ...

    parent_mcp.mount(sub, prefix=self.name)
```

Now both tools appear as `molpack_list_pack_targets` and `molpack_get_pack_target`. This is the recommended pattern when multiple MolCrafts Providers will be loaded together.

### Marking destructive tools

Most stateful-query tools that survive the four-condition rule are read-only. If a tool legitimately needs to mutate external state, mark it explicitly so MCP clients prompt the user:

```python
@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def reset_workspace_lock(workdir: str) -> str:
    """Clear a stale workspace lock left by a crashed session."""
    ...
```

`destructiveHint=True` tells the MCP client this tool mutates external state. Most clients will prompt the user before each call. If your tool both reads and writes, set `destructiveHint=True` (it dominates). Reach for this annotation sparingly — anything that *runs* a simulation, packs a box, or writes scientific output usually belongs in upstream's API/CLI rather than as a tool, per [Provider design](../concepts/provider-design.md).

### Shelling out to external tools

If your Provider has a legitimate reason to call an external CLI (Packmol, LAMMPS, AmberTools, …), **do not** use `subprocess.run` directly. Use molmcp's `run_safe`:

```python
from molmcp import run_safe

@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def run_packmol(input_file: str, workdir: str) -> dict:
    """Run packmol against an input file in workdir."""
    result = run_safe(
        ["packmol"],
        cwd=workdir,
        timeout=120.0,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
```

`run_safe` enforces list-form args (no shell injection), no `shell=True`, mandatory timeout, output truncation. See **[Security](security.md)** for the full story. (And re-read the four-condition rule before shipping a tool that runs an external process — most "run X" tools should be invocations the agent scripts itself after introspecting upstream.)

## Read next

- **[Provider design](../concepts/provider-design.md)** — the four-condition rule that decides whether your tool should exist
- **[Security](security.md)** — `run_safe`, `fence_untrusted`, what to validate
- **[Middleware](../concepts/middleware.md)** — how molmcp's defaults wrap your tools
