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

## Multi-language by design

The `LanguageAnalyzer` protocol and the shared graph schema are the
multi-language design. The Python analyzer is real today; TypeScript,
Rust, and C++ are registered stubs that declare their file extensions
and slot in behind the same interface — a new analyzer needs no schema,
store, or tool changes.

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
