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

**First-party MolCrafts packages (molq, molexp, …):** implement the provider
**in molmcp**, not in the upstream package:

```
molmcp/src/molmcp/providers/<name>/
  __init__.py
  provider.py
```

Register via molmcp's `pyproject.toml` entry point
`molmcp.providers.<name>`. Lazy-import the upstream package inside
`register()` / tool bodies. Do **not** add FastMCP to molq/molexp core.

**Third-party / external packages:** use a sibling package named
`<pkg>_mcp` (or an optional `mcp` extra in your own repo):

```
molpack/                 # the main package, no MCP knowledge
└── src/molpack/...

molpack_mcp/             # sibling package, the Provider
└── src/molpack_mcp/__init__.py
```

That keeps MCP out of your main package's import graph for consumers who
never run an MCP server.

## Step 3 — Write the Provider class

Create `molpack_mcp/__init__.py`:

```python
"""MCP Provider for molpack."""
from __future__ import annotations

from molmcp.providers.annotations import READ_ONLY
from molmcp.providers.base import ProviderBase, tool


class MolpackProvider(ProviderBase):
    name = "molpack"
    upstream = "molpack"      # what to `pip install` when it is missing
    import_name = "molpack"   # what to probe for

    @tool(READ_ONLY)
    def list_pack_targets(self, workdir: str) -> list[dict]:
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

There is no `register()` to write. `ProviderBase` collects every method
carrying a `@tool` declaration, checks the upstream package once, and
registers them. The method is handed to FastMCP already bound, so `self`
never reaches the tool schema and the docstring the agent reads is the one
you wrote.

A few things worth calling out:

- **Earned its slot.** `list_pack_targets` reads runtime state (the on-disk catalog) — exactly the kind of question introspection over `molpack` source cannot answer. Stable signature, read-only, every-session frequency, single-shot answer: passes [the four conditions](../concepts/provider-design.md). A `pack_box(spec, workdir)` tool that *runs* the packing would fail condition 2 (mutating, file-writing) and belongs in upstream's API/CLI instead.
- **Class-level `name = "molpack"`.** The plane id, the dedup key, and the
  MCP server name. A client shows `molpack__list_pack_targets`; the tool
  itself registers **bare**, and startup rejects a `molpack_`-prefixed name.
- **An annotation constant, not a literal.** Pick from
  [`molmcp.providers.annotations`](#annotations): `READ_ONLY`,
  `READ_REMOTE`, `IDEMPOTENT_WRITE`, `APPEND_WRITE`, `LOCAL_MUTATION`,
  `MUTATION`. Annotations are required — molmcp refuses to start a server
  whose tools do not declare them.
- **`upstream` / `import_name`.** The base uses these for one job: telling a
  user which package to install. `probe()` asks the import system whether
  the module *could* be imported rather than importing it, so listing the
  plane catalog never drags a scientific stack into the process.
- **Lazy import of the upstream module.** Don't `import molpack` at module
  top — auto-discovery instantiates your Provider just to read its name, and
  that must stay cheap. Defer the import into the tool body.
- **Plain-dict return.** Don't return Pydantic models from tool functions; some MCP clients serialize them as JSON-strings instead of dicts. Stick to primitives, lists, dicts.

### A tool whose name is a Python keyword

`open` is a builtin and `exec` is a keyword, so neither can be a method
name. Give the declaration the wire name instead:

```python
@tool(MUTATION, name="exec")
def exec_code(self, session_id: str, code: str) -> dict:
    """Run Python in a session's namespace."""
```

### Annotations

| Constant | Use for | destructive | idempotent | open world |
|----------|---------|:-----------:|:----------:|:----------:|
| `READ_ONLY` | reads local state | no | yes | no |
| `READ_REMOTE` | reads, but asks a scheduler or the network | no | no | yes |
| `IDEMPOTENT_WRITE` | create-or-get; twice leaves one thing | no | yes | no |
| `APPEND_WRITE` | adds to a local record; twice adds twice | no | no | no |
| `LOCAL_MUTATION` | rewrites or removes local state, resumably | yes | yes | no |
| `MUTATION` | changes state beyond this machine | yes | no | yes |

Destructiveness and reach are independent axes — a tool that deletes local
files is destructive but closed-world, and one that queries a cluster is
open-world but harmless. Pick the row that is true; if none is, add a
constant to that module with the reason rather than building one inline.
Inline literals are how the values drifted apart in the first place.

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

Run with `pytest tests/test_mcp.py -v`. A provider plane carries only its own tools; the knowledge tools live on the separate `molcrafts` plane.

## Step 6 — Use it from an MCP client

The user installs your package and starts the server:

```bash
pip install molpack[mcp]
molmcp planes          # molpack now appears
molmcp serve molpack   # one plane, one process
```

Auto-discovery finds the entry point, so the plane is listed and servable.
Because `molpack` is an importable MolCrafts distribution, the knowledge
plane also indexes it — its symbols are reachable through `molcrafts`
`search` / `open`, separately from your tools.

To wire into a client:

```bash
molmcp client            # every plane, as standard mcpServers JSON
claude mcp add molpack -- molmcp serve molpack
```

## Patterns worth knowing

### Bare tool names only (no mount prefix)

Each provider is its **own** MCP plane (`molmcp serve molpack`). Register
**bare** tool names — never prefix with the plane id, and never
`parent.mount(sub, namespace=...)`.

```python
class MolpackProvider(ProviderBase):
    name = "molpack"

    @tool(READ_ONLY)
    def list_pack_targets(self, workdir: str) -> list[dict]: ...

    @tool(READ_ONLY)
    def get_pack_target(self, workdir: str, name: str) -> dict: ...
```

Client ids become `molpack__list_pack_targets`. Startup **rejects** tools
named `molpack_list_pack_targets` (would become `molpack__molpack_…` or
legacy `molpack_molpack_…`).

### Marking destructive tools

Most stateful-query tools that survive the four-condition rule are read-only. If a tool legitimately needs to mutate external state, mark it explicitly so MCP clients prompt the user:

```python
@tool(LOCAL_MUTATION)
def reset_workspace_lock(self, workdir: str) -> str:
    """Clear a stale workspace lock left by a crashed session."""
    ...
```

A destructive hint tells the client the call is not freely repeatable, and
most clients prompt before each one. Pick `LOCAL_MUTATION` when the damage
is confined to this machine and `MUTATION` when it reaches beyond it —
conflating the two makes a local file operation claim it talks to the
world, and a client cannot then tell the two risks apart.

Reach for a destructive tool sparingly. Anything that *runs* a simulation,
packs a box, or writes scientific output usually belongs in upstream's
API/CLI rather than as a tool, per
[Provider design](../concepts/provider-design.md).

### Shelling out to external tools

If your Provider has a legitimate reason to call an external CLI (Packmol, LAMMPS, AmberTools, …), **do not** use `subprocess.run` directly. Use molmcp's `run_safe`:

```python
from molmcp import run_safe

@tool(MUTATION)
def run_packmol(self, input_file: str, workdir: str) -> dict:
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
