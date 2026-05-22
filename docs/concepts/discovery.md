# Discovery engine

molmcp's core capability is **discovery**: helping an agent find out
what a codebase actually provides, instead of guessing function, class,
or tool names. It does this by statically indexing a codebase into a
**code graph** and answering structured queries against it.

The engine lives in `molmcp.discovery` and is MCP-free — it can be
imported, scripted, and tested without FastMCP. The MCP interface
(`molmcp.discovery.provider`) is a thin shell on top.

## The pipeline

```
source spec ─► SourceResolver ─► Snapshot ─► Extractor ─► Resolver ─► GraphStore
  pkg:molpy                       (immutable,  (phase 1)   (phase 2)   (SQLite
  /path/to/repo                    content-                            graph.db)
  github:owner/repo@ref            hashed)
```

1. **Source resolution.** A spec — a local path, `pkg:<name>` for an
   installed package, or `github:owner/repo@ref` — is resolved to an
   immutable `Snapshot`. The snapshot is identified by a **content
   hash** (local) or **commit SHA** (GitHub), never a branch name.
   GitHub sources resolve the ref to a commit, download that commit's
   tarball into the cache, and are then indexed exactly like local
   source.
2. **Extraction (phase 1).** Each file is dispatched by extension to a
   `LanguageAnalyzer`. The Python analyzer (stdlib `ast`) emits modules,
   classes, functions, methods, properties, fields, constants,
   decorators, signatures, docstrings, and `contains` edges, plus
   *unresolved references* for calls, base classes, and imports.
3. **Resolution (phase 2).** The `Resolver` links unresolved references
   to nodes within the snapshot, resolves relative imports, links pytest
   tests to the symbols they exercise, and lifts docstring code blocks
   into first-class `example` nodes. Genuinely dynamic references are
   kept as unresolved so they degrade gracefully.
4. **Storage.** The graph is written to one SQLite `graph.db` per
   snapshot, with a derived FTS5 index for symbol search.

## The graph

Every analyzer emits the same language-agnostic schema:

- **Nodes** — `file`, `package`, `module`, `class`, `function`,
  `method`, `property`, `field`, `constant`, `example`, `test`,
  `capability`, and more. Each carries kind, qualname, file, line span,
  signature, docstring, and flags.
- **Edges** — `contains`, `calls`, `extends`, `imports`, `exemplifies`,
  `tests`, `provides_capability`, and more. Each carries a `provenance`
  (`ast` / `heuristic` / `resolved`).

`example` and `test` are first-class node kinds, so an agent can ask
"show me usage of X" and "what tests X" as graph queries.

## Snapshots, cache, and freshness

The cache lives under `~/.cache/molmcp/discovery/` (override with
`MOLMCP_CACHE_DIR`). Every snapshot gets its own directory, keyed on its
snapshot id:

```
<cache>/snapshots/<snapshot-slug>/
    manifest.json
    graph.db
```

Because the snapshot id is a content hash, a cached graph is always tied
to exact source. When a file changes, the next index produces a new
snapshot id and a new directory — the old one is untouched. Every tool
response carries a `snapshot` block so an agent knows which revision it
is looking at.

Re-indexing is **incremental**: a content-addressed `ExtractCache` lets
unchanged files skip the analyzer, so only edited files are re-parsed.
Local sources are re-resolved on every query (always fresh); GitHub
sources are cache-first to respect API rate limits — call
`molmcp_refresh` to pull a newer commit. The cache is bounded by
`max_snapshots_per_spec` and `max_cache_age_days`, pruned automatically.
An optional `LocalWatcher` polls a local source and refreshes it on
change.

## Multi-language by design

The `LanguageAnalyzer` protocol and the shared graph schema are the
multi-language design. The Python analyzer is real today; TypeScript,
Rust, and C++ are registered stubs that declare their file extensions
and slot in behind the same interface — a new analyzer needs no schema,
store, or tool changes.

## Domain capability overlays

molmcp core is domain-agnostic. Domain knowledge — "this codebase
provides a *radial distribution function* capability" — is layered on
top through an **overlay**, without core ever importing the domain
package.

An overlay implements the `CapabilityOverlay` protocol (`name`,
`applies_to`, `contribute`). After resolution, the engine calls each
overlay's `contribute(graph)` and merges the returned `capability`
nodes and `provides_capability` edges into the graph — so every
discovery tool then works on capabilities for free.

The simplest overlay is a `CatalogOverlay` built from a domain-agnostic
`capability_catalog.toml`:

```toml
[[capability]]
id = "compute.rdf"
title = "Radial distribution function"
summary = "Compute g(r) between atom selections."
implemented_by = ["molpy.compute.rdf.RDF"]   # qualnames -> graph nodes
examples = ["examples/rdf_basic.py"]
tags = ["analysis", "structure"]
```

Each `implemented_by` qualname is resolved against the code graph into a
`provides_capability` edge; a qualname that does not resolve is kept
visibly in `unresolved` rather than dropped.

Overlays are discovered via the `molmcp.overlays` entry-point group,
exactly like providers:

```toml
[project.entry-points."molmcp.overlays"]
molpy = "molpy_overlay:MolpyOverlay"
```

Remove every overlay and the engine still works — it is just a
domain-agnostic code-discovery engine.

## Using it without MCP

```python
from molmcp.discovery import DiscoveryEngine

engine = DiscoveryEngine()
query = engine.query("pkg:molpy")
for node in query.search("radial distribution function"):
    print(node.qualname, node.file, node.start_line)
```

Or from the CLI:

```bash
molmcp discovery index pkg:molpy
molmcp discovery outline pkg:molpy
molmcp discovery query pkg:molpy "structure reader"
molmcp discovery dump pkg:molpy --output graph.json
```

## Verifying it works

There are four ways to confirm discovery is healthy, from quickest to
most thorough.

**1. The built-in self-check.** `molmcp discovery verify` indexes a
source and prints a health report — counts, FTS status, and a sample
query — exiting non-zero on failure, so it works in CI or a setup
script:

```bash
molmcp discovery verify pkg:molpy
```

**2. The test suite.** The engine ships with focused tests:

```bash
pytest tests/discovery -q
```

**3. The Python API**, with no MCP client involved:

```python
from molmcp.discovery import DiscoveryEngine

query = DiscoveryEngine().query("pkg:molpy")
hits = query.search("radial distribution function")
assert hits, "expected at least one match"
print(hits[0].qualname, hits[0].file, hits[0].start_line)
```

**4. The MCP tool path.** Run `python -m molmcp --source pkg:molpy` and
call the tools — every response carries a `snapshot` block with a
`freshness` status. The key property to check: an agent never invents a
name. The flow is `molmcp_outline` → `molmcp_search_symbols` /
`molmcp_find_capability` (which return real qualnames) →
`molmcp_describe_symbol` / `molmcp_relations`; a wrong qualname yields a
structured `{"error": …}`, never a hallucinated result.

The graph itself is plain SQLite — open
`~/.cache/molmcp/discovery/snapshots/<slug>/graph.db` with any SQLite
browser to inspect the `nodes`, `edges`, and `files` tables directly.
