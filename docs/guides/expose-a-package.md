# Expose a MolCrafts package

Walkthrough: take any MolCrafts package and index it for discovery via MCP.

## The minimal case

```bash
python -m molmcp
```

That's enough — molmcp auto-detects every installed MolCrafts package and indexes them all for the six discovery tools. Below we walk through what the agent actually sees, using `molpy` as the running example.

If you want a server scoped to one package only, narrow with `--source`:

```bash
python -m molmcp --source pkg:molpy
```

A `--source` spec is a local path, `pkg:<name>` for an installed package, or `github:owner/repo[@ref]` for a GitHub repository.

## How indexing works

The first time a source is queried, the discovery engine resolves the spec to an immutable **snapshot**, statically parses every file into a **code graph** — symbols, signatures, docstrings, calls, base classes, imports, examples, tests — and stores that graph as one SQLite database keyed on a content hash. Re-indexing is incremental: unchanged files skip the analyzer. See **[Discovery engine](../concepts/discovery.md)** for the full pipeline.

You can index ahead of time, or just inspect a source, with the CLI:

```bash
molmcp discovery index pkg:molpy
```

## The six tools, by example

### `molmcp_outline`

The "where do I look" tool — call it first to see a source's structure.

```python
from molmcp import create_server
import asyncio

server = create_server(
    "molpy",
    discovery_sources=["pkg:molpy"],
    discover_entry_points=False,
)

async def main():
    result = await server.call_tool("molmcp_outline", {})
    print(result.content[0].text)

asyncio.run(main())
```

Output (excerpt):

```json
{
  "modules": [
    {
      "kind": "module",
      "qualname": "molpy.core.atomistic",
      "file": "molpy/core/atomistic.py",
      "symbols": [
        {"kind": "class", "name": "Atom"},
        {"kind": "class", "name": "Atomistic"},
        {"kind": "class", "name": "Bond"}
      ]
    }
  ],
  "snapshot": {"snapshot_id": "...", "spec": "pkg:molpy", "freshness": "fresh"}
}
```

The whole package mapped from packages/modules down to their symbols. With `path="molpy/core"`, only that subtree. Every response carries a `snapshot` block so the agent knows which revision it is looking at.

### `molmcp_find_capability`

The primary tool. Describe a task in natural language; get ranked symbol matches, each with signature, summary, usage examples, tests, and callers.

```python
await server.call_tool(
    "molmcp_find_capability",
    {"task": "compute a radial distribution function", "max_results": 8},
)
```

Output (excerpt):

```json
{
  "query": "compute a radial distribution function",
  "match_count": 1,
  "matches": [
    {
      "rank": 1,
      "node": {
        "qualname": "molpy.compute.rdf.RDF",
        "kind": "class",
        "file": "molpy/compute/rdf.py",
        "start_line": 12
      },
      "signature": "RDF(selection_a, selection_b, r_max, n_bins=200)",
      "summary": "Radial distribution function between two atom selections.",
      "examples": [{"file": "molpy/compute/rdf.py", "code": "..."}],
      "tests": [{"qualname": "test_rdf.test_oo_rdf", "file": "tests/test_rdf.py"}],
      "callers": []
    }
  ],
  "snapshot": {"snapshot_id": "...", "spec": "pkg:molpy", "freshness": "fresh"}
}
```

This is how an agent resolves a capability from real, indexed code instead of guessing function or class names.

### `molmcp_search_symbols`

Full-text search over indexed symbols by name, qualname, or summary.

```python
await server.call_tool(
    "molmcp_search_symbols",
    {"query": "reader", "kind": "class", "max_results": 30},
)
```

`kind` is an optional node-kind filter (`class`, `function`, `method`, `test`, …). Returns one brief per match — qualname, kind, file/line, one-line summary — useful as a hub-and-spoke navigation aid: search first, then `molmcp_describe_symbol` on the interesting one.

### `molmcp_describe_symbol`

Full detail for a single symbol — pass a qualname taken from a prior search or outline result, never a guessed one.

```python
await server.call_tool(
    "molmcp_describe_symbol",
    {"qualname": "molpy.core.atomistic.Atomistic", "include_source": True},
)
```

Returns the symbol's kind, signature, cleaned docstring, file/line span, and — with `include_source=True` — its full source code, decorators included. The same call works for modules, classes, methods, and functions.

### `molmcp_relations`

Walk the code graph from one symbol along a single relation.

```python
await server.call_tool(
    "molmcp_relations",
    {"qualname": "molpy.compute.rdf.RDF", "relation": "callers"},
)
```

`relation` is one of `callers`, `callees`, `implementers`, `subclasses`, `implementations`, `references`, `examples`, `tests`, `impact`. So "show me usage of `RDF`" is `relation="examples"`, "what tests it" is `relation="tests"`, and "what breaks if I change it" is `relation="impact"` (with a `depth` of 1–4 hops).

### `molmcp_refresh`

Force a fresh re-index of a source. Indexing is otherwise lazy and automatic — local sources are always re-checked, GitHub sources are cache-first — so reach for this only to rebuild a graph on demand.

```python
await server.call_tool("molmcp_refresh", {})
```

## Multi-package setups

The default already indexes every installed MolCrafts package as a separate source. The agent passes a `source` argument on any tool to scope a query to one of them, or omits it to use the default. Useful when an agent is doing comparative work across the ecosystem — e.g., wiring up a `molexp` experiment that calls into `molpack`.

Pass `--source` explicitly only when you need to *narrow* (one package), *extend* (a local checkout, another package), or index something outside the default set:

```bash
python -m molmcp --source pkg:molpy --source /path/to/a/repo --source github:MolCrafts/molpack
```

## When discovery isn't enough

The six tools tell the agent *what's in the source* — symbols, signatures, examples, relationships. For domain capabilities — "build a polymer in molpy", "pack a box with molpack", "submit a job through molq" — the agent discovers the API and runs the upstream API/CLI itself; that's the discovery-first loop molmcp is built around.

A Provider only enters the picture when the question depends on something static analysis can't reach — local runtime state (a jobs DB, a workspace catalog, an OS-level config), a native extension the code graph can't index, or an external DSL. `MolqProvider` and `MolexpProvider` are the canonical runtime-state examples; `MolpyProvider`, `MolpackProvider`, and `LammpsProvider` cover the other cases. Read **[Provider design](../concepts/provider-design.md)** for the four-condition rule, then **[Write a Provider](write-a-provider.md)** for the mechanics.
