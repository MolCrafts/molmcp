# Expose a MolCrafts package

Index a MolCrafts package for **knowledge** on the `molcrafts` plane, or ship a
**provider plane** for live state the graph cannot answer.

## Knowledge only (no custom Provider)

If the package is an installed MolCrafts distribution, nothing is needed:
auto-discovery finds anything declaring a `molmcp.*` entry point or the
`molcrafts` keyword. Otherwise name it as a source.

```bash
molmcp config set sources.molpy pkg:molpy
molmcp config set indexWorkspace true --project   # index this checkout too

molmcp serve molcrafts
# client tool: molcrafts__packages → molcrafts__outline → molcrafts__open
```

Source specs:

- `path/to/repo` — local directory
- `pkg:<name>` — installed import name
- `local:<package-dir>` — a package directory in a foreign environment
- `github:owner/repo[@ref]` — GitHub at a resolved commit

Check what is actually in scope with `molmcp config list`.

Pre-index offline:

```bash
molmcp index
molmcp search "RDF" --source molpy
```

## What the agent does on molcrafts

| Step | Tool | Purpose |
|------|------|---------|
| 1 | `packages` | Choose which source(s) matter |
| 2 | `outline` | Map modules / symbols |
| 3 | `search` / `suggest` | Optional index helpers |
| 4 | `open` | Inject one symbol page into context |
| 5 | (agent Python) | Call the real API — not an MCP science tool |

```python
from molmcp import create_plane, load_config

mcp = create_plane("molcrafts", config=load_config())  # settings + auto-discovery
# In a client: packages() → open("molpy.compute.rdf.RDF")
```

## Shipping a provider plane

When the graph cannot answer (jobs, live viewer session, workspace layout),
ship a `Provider` as its **own** plane:

```toml
[project.entry-points."molmcp.providers"]
molpack = "molpack_mcp:MolpackProvider"
```

```bash
molmcp serve molpack    # server name = provider.name
# tools: molpack__…
```

Four-condition rule and protocol: [Provider design](../concepts/provider-design.md),
[Write a Provider](write-a-provider.md).

## How indexing works

First query resolves a source to an immutable **snapshot**, parses into a
SQLite **code graph**, and caches by content hash / commit. Unchanged files
skip re-analysis. See [Discovery engine](../concepts/discovery.md).

## Read next

- [Quickstart](../get-started/quickstart.md)
- [Architecture](../concepts/architecture.md)
- [MolVis workbench](molvis-workbench.md)
