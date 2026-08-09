# Providers

A **Provider** is one product's MCP surface: the plane `molmcp serve <name>`
runs. It exists for what the discovery engine cannot answer on its own —
stateful runtime data (a job database, an on-disk workspace), a live in-process
session, or a capability behind a native extension that source discovery cannot
read.

One process serves **one** provider. There is no mega-server and no mounting:
`create_plane("molq")` builds a server named `molq` holding that provider's
tools and nothing else. Passing more than one raises.

> **Read [provider-design.md](provider-design.md) first.** It defines the
> conditions a tool must satisfy before earning a slot. Most ideas for new
> tools fail one — the answer is usually "let the agent discover the API and
> script it" rather than adding a tool.

## The contract

A provider subclasses `ProviderBase` and **declares** its tools. It does not
register them:

```python
from molmcp.providers.annotations import READ_ONLY
from molmcp.providers.base import ProviderBase, tool


class MolqProvider(ProviderBase):
    name = "molq"                 # must equal the plane id you serve
    upstream = "molcrafts-molq"   # distribution named in the missing-package error
    import_name = "molq"          # module the availability probe looks for

    @tool(READ_ONLY)
    def list_jobs(self, limit: int = 20) -> list[dict]:
        """List recent jobs."""
        ...
```

Three class attributes and one decorator per tool. `ProviderBase.register()`
collects every method carrying `@tool(...)`, checks the upstream package once,
and attaches them — so a provider holds only what is actually its own: what the
tools do.

Each provider used to carry its own `register()` method — 349, 402 and 191
lines of nested functions, each with its own availability probe, its own
missing-package message, and hand-rolled annotations that had drifted out of
agreement. Declaring instead of registering is what removed that.

`register()` refuses two methods claiming one wire name. Overriding by
*attribute* is intended — a subclass redefining a tool replaces it — but two
distinct methods claiming one name means one silently shadows the other,
decided by MRO order.

## Availability is a probe, not an import

`probe()` asks the import system whether the upstream package *could* be
imported; it never imports it. A catalog listing must not drag a scientific
stack into a process that only wanted to print a list.

Override it when availability is not simply "the package is present" — molvis
is available whenever a stage factory has been injected, browser or no browser.

When the package is missing, the plane fails at build time with a message
naming the distribution and how to install it:

```
RuntimeError: the 'molq' plane requires the 'molcrafts-molq' package.
Install with: pip install molcrafts-molq
```

## Registration

A provider reaches molmcp through the `molmcp.providers` entry-point group:

```toml
[project.entry-points."molmcp.providers"]
molq = "molmcp.providers.molq:MolqProvider"
```

`molmcp serve molq` loads the entry point whose name matches the plane id and
serves that provider alone. **Every provider is instantiated with `cls()`** —
no arguments. Anything an operator must be able to change therefore belongs in
settings (`molmcp config set …`), never in a constructor keyword, which no MCP
client can reach.

Constructor keywords remain the seam for embedders and tests: injecting a
provider's backends is what lets its tools be exercised without the science
package installed.

## Namespacing

The MCP **server name is the plane id**. Tools register with bare names
(`list_jobs`, `open`, …) and a client sees `molq__list_jobs`. Different
products never share a tool namespace because they never share a process.

Tool names in `hint` and error strings must therefore be written **bare**, as
registered — `tests/test_tool_hints.py` enforces it. A hint naming a spelling
no client resolves turns the error message into the next error.

## Annotation requirement

Every tool must declare its annotations, from the shared vocabulary in
`molmcp.providers.annotations`: `READ_ONLY`, `READ_REMOTE`, `IDEMPOTENT_WRITE`,
`APPEND_WRITE`, `LOCAL_MUTATION`, `MUTATION`.

```python
@tool(READ_ONLY)
def get_atom_count(self, filename: str) -> int:
    """Count atoms in a structure file."""
    ...

@tool(MUTATION)
def write_pdb(self, structure: dict, path: str) -> None:
    """Write structure to a PDB file (overwrites existing)."""
    ...
```

The [annotations validator](middleware.md#annotations-validator) walks every
registered tool at build time and refuses to start the server if one is
missing. MCP clients use these hints to decide whether to auto-approve a call:
without them the user is either prompted for every call, or everything is
auto-approved. Both degrade the whole ecosystem's UX.

## Discovery hygiene

Auto-discovery is a trust boundary — any installed package declaring the entry
point can offer a plane. molmcp:

- skips providers that fail to instantiate, recording the failure rather than
  crashing;
- omits planes whose upstream package is absent from catalogs and generated
  client configs, silently, since an uninstalled product is not an error;
- still fails loudly when you ask for such a plane by name, because
  `molmcp serve molq` is an explicit request.

## First-party providers

Three, each an entry point in this repo's `pyproject.toml`:

| Provider | Plane | Why it cannot be discovery |
|---|---|---|
| `MolqProvider` | `molq` | Reads live job-database state. Read-only tools plus `submit_job` / `cancel_job`, off until `molq.allowSubmit` is set. |
| `MolexpProvider` | `molexp` | Reads an on-disk workspace catalog; serves the layout contract, a read-only linter, and a resumable hash-verified adoption of a legacy data directory. |
| `MolvisProvider` | `molvis` | Drives a live in-process viewer session — an object being mutated now, which no static index of the source can describe. |

Third-party packages ship a sibling `*_mcp` package declaring the same
entry-point group. The same design rule applies: a provider that re-exports an
upstream API as MCP tools will be flagged in review.

## Read next

- **[Provider design](provider-design.md)** — what earns a tool slot, and what not to ship.
- **[Middleware](middleware.md)** — what wraps a provider's tools.
- **[Write a Provider](../guides/write-a-provider.md)** — step-by-step.
