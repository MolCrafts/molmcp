# MolMCP vNext — MolCrafts LLM Context Plane

Status: core implementation complete; ecosystem integration pending
Target release: `0.3.0` (clean break; no compatibility requirement)
Date: 2026-07-10

Implementation checkpoint:

- Phases 1–4 are implemented in this repository: strict registry and digest
  boundary, federated collection/context API, multi-language analyzers and
  cache v4, four-tool MCP, clean CLI/config, namespaced providers, lifecycle,
  resources, authentication gates, and removal of legacy in-tree facades.
- Remote manifests without a configured matching digest are registered with
  `execution_status = "search_only"`; their declarations remain discoverable
  but cannot produce an executable Molexp handoff.
- Phase 5 is intentionally cross-repository work: official manifests and
  package-owned adapters must land in the corresponding MolCrafts packages.

## 1. Objective

Rebuild MolMCP as the local-first LLM context plane for the full MolCrafts
ecosystem. It must let an agent:

1. discover which MolCrafts package and capability applies to a task;
2. inspect the exact API, examples, constraints, and source evidence;
3. distinguish explanatory code hits from explicitly executable actions;
4. hand executable capability manifests to Molexp for planning, approval,
   execution, artifacts, and audit;
5. inspect Molexp and Molq runtime state through package-owned, read-only
   providers.

MolMCP owns registry, indexing, retrieval, context packing, MCP transport,
and provider loading. It does not own workflow orchestration, approval,
subprocess execution, job scheduling, artifact lineage, or durable scientific
memory.

## 2. Hard boundaries

### 2.1 Discovery is not execution

`DiscoveryHit` is evidence that code or documentation exists. It is never an
executable contract.

Only a validated `ExecutableCapabilityV1` loaded from a package-owned manifest
may enter a Molexp `CapabilityRegistry`. Missing or invalid invocation,
side-effect, input, output, backend, or provenance data makes an item
non-executable. There is no inference fallback from a Python signature.

### 2.2 Ecosystem ownership

| Layer | Owner |
|---|---|
| Registry, source snapshots, code/doc graph, retrieval, context packs | MolMCP |
| Experiment planning, approvals, execution, artifacts, audit, knowledge | Molexp |
| Local/HPC job lifecycle, scheduler state, retry, cancel, logs | Molq |
| GitHub issue/agent orchestration | Symphony, optional and not a core dependency |

Package-specific providers must depend on public upstream APIs and ship with
the upstream package or a separately versioned adapter. MolMCP core must not
mirror changing upstream internals.

### 2.3 First-release non-goals

- No conversational, ADR, episodic, or scientific-memory database in MolMCP.
- No arbitrary Cypher/SQL query MCP tool.
- No raw shell execution.
- No automatic client configuration, hooks, telemetry, or self-update.
- No claim of universal language support. First-class languages are Python,
  Rust, TypeScript/JavaScript, Markdown, JSON, and TOML.
- No remote multi-tenant service in the first implementation. Streamable HTTP
  remains available only when explicit authentication and workspace isolation
  are configured.

## 3. Public data contracts

All wire contracts are JSON-serializable, versioned, validated strictly, and
implemented without importing MCP machinery.

### 3.1 Stable identifiers

- Registry item: `@<namespace>/<name>`, for example `@molpack/pack` or
  `@molpy/analysis.rdf`.
- Source: a configured source name plus immutable snapshot identity.
- Symbol: `<source>@<snapshot>:<file>#<qualname>#<kind>`.
- Registry IDs are independent of Python import paths and remain stable across
  implementation refactors.

### 3.2 `CatalogItemV1`

Required fields:

- `schema_version = "1"`
- `id`, `kind`, `title`, `summary`
- `package`, `package_version`
- `tags`, `aliases`
- `examples`
- `provenance` containing source URI, revision, manifest digest, and declarer

Supported non-executable kinds are `concept`, `recipe`, `convention`, and
`validator`. These items improve retrieval and may link to code symbols, but
cannot be invoked.

### 3.3 `ExecutableCapabilityV1`

Extends `CatalogItemV1` with `kind = "executable"` and requires:

- `invocation.kind`: exactly one of `python`, `cli`, or `mcp`;
- `invocation.target`: callable path, argv template, or MCP tool name;
- `input_schema` and `output_schema`: JSON Schema objects;
- `side_effects`: an explicit list, including an explicit empty list;
- `supported_backends`;
- `requirements`: packages, executables, platform constraints;
- `validators`;
- `timeout_seconds` and resource class.

Scientific annotations use namespaced JSON Schema extensions:

- `x-molcrafts-unit`
- `x-molcrafts-dimension`
- `x-molcrafts-coordinate-frame`
- `x-molcrafts-index-base`
- `x-molcrafts-artifact-kind`

`@molpack/pack` is a single fixed packing workflow: molecule templates,
counts, restraints/PBC, and output. Individual restraints are discoverable
types, not independent workflow actions.

### 3.4 Manifest and registry resolution

- Package manifest filename: `molcrafts.registry.json`.
- Installed packages expose manifests through the new
  `molmcp.capabilities` entry-point group.
- Project configuration is `molcrafts.json` at the workspace root.
- Registry sources may be installed entry points, local files/directories, or
  HTTPS URL templates using `@namespace` addressing.
- Authentication values are environment-variable references and are never
  included in logs or tool responses.
- Duplicate IDs, incompatible versions, dependency cycles, or conflicting
  scientific metadata fail closed. There is no last-write-wins merge.
- Any manifest used for execution must be pinned by package version and content
  digest. Floating `latest` content is search-only.

## 4. Index and retrieval architecture

### 4.1 Per-source graph

Each immutable source snapshot has a separate SQLite graph. Graph facts carry
source span and provenance. The graph schema is rebuilt as version 4 and old
caches are discarded.

Primary analyzers:

- Python: stdlib `ast`, retaining exact signatures and docstrings.
- Rust: Tree-sitter definitions/imports/calls plus optional SCIP ingestion.
- TypeScript/JavaScript: Tree-sitter definitions/imports/calls plus optional
  SCIP ingestion.
- Markdown: headings, prose sections, fenced examples, and symbol references.
- JSON/TOML: package metadata, registry/config keys, and selected DSL records.

Edges use explicit provenance: `ast`, `tree_sitter`, `scip`, `resolved`, or
`heuristic`. Heuristic call edges never affect ranking.

### 4.2 Collection index

`CollectionIndex` owns named `SourceBinding` objects and a `Registry`. It does
not merge source databases. It provides:

- federated search across registry items, symbols, docs, examples, and tests;
- normalized source identity and deterministic result ordering;
- cross-package dependency edges stored separately from source graphs;
- collection-wide freshness and coverage reporting;
- source-local failure isolation.

Omitting a source always searches the full collection. Selecting one or more
source names is an explicit filter; no source is silently chosen.

### 4.3 Retrieval

Candidate channels:

1. exact registry ID, aliases, tags, and symbol names;
2. field-weighted BM25 over catalog, symbols, docs, and examples;
3. bilingual MolCrafts domain aliases and Unicode-aware query normalization;
4. optional semantic candidates, disabled by default.

Channels are combined with reciprocal-rank fusion. Reliable graph edges may
attach examples, tests, call paths, and impact evidence only after anchors are
selected. Graph degree is never the primary retrieval signal.

### 4.4 Cache identity and freshness

The graph build identity includes:

- source content snapshot;
- graph schema version;
- analyzer and resolver versions;
- analyzer configuration;
- overlay/registry manifest digest;
- MolMCP engine version.

Writes use a process lock, temporary database, fsync, and atomic replacement.
Queries expose `fresh`, `stale`, `pending`, or `unknown`; they never silently
return known-stale code. A file watcher performs debounced changed-file
re-indexing and a connect-time content-hash reconciliation.

## 5. Context API

### 5.1 `SearchHit`

Every hit contains:

- stable `ref` and `kind`;
- namespace/source/snapshot;
- title, summary, signature where relevant;
- `executable` boolean and optional executable capability ID;
- score channel and provenance;
- freshness and source span.

### 5.2 `ContextPack`

`ContextBuilder.explore(task, ...)` returns one bounded package containing:

- resolved task and applied filters;
- ranked registry capabilities and explanatory code/doc anchors;
- exact signatures and compact source snippets;
- examples, tests, conventions, and reliable graph relationships;
- installed-version/backend compatibility warnings;
- snapshot/freshness/coverage data;
- suggested next actions, expressed only with resolved IDs;
- explicit truncation and unresolved sections.

Default output budget is 16,000 characters; hard maximum is 32,000. Section
allocation is deterministic, and each truncated section reports omitted counts.

## 6. MCP surface

The default MolMCP server exposes exactly four core, read-only tools:

### `molcrafts_info(workspace: str | None = None)`

Returns collection sources, registries, installed versions, enabled providers,
backend availability, index coverage/freshness, and configuration warnings.

### `molcrafts_search(query, kinds=None, namespaces=None, sources=None, limit=20)`

Returns compact `SearchHit` records. It searches the full collection unless
filters are explicit.

### `molcrafts_describe(ref, include_source=False, include_examples=True)`

Returns full detail for a registry item or indexed symbol. `ref` must come from
a prior result; guessing is not accepted when a ref is ambiguous.

### `molcrafts_explore(task, namespaces=None, sources=None,
budget_chars=16000)`

Primary agent tool. Returns a `ContextPack` suitable for answering or handing
off to Molexp.

Resources mirror the same data:

- `molcrafts://workspace/context`
- `molcrafts://capability/{namespace}/{name}`
- `molcrafts://source/{source}/symbol/{symbol}`

Validated recipe catalog items may be exposed as dynamic MCP prompts.

Package-owned providers continue to use the `molmcp.providers` entry-point
group. MolMCP mounts each provider into an automatic namespace. Mutation tools
belong to the owning package and must use MCP annotations plus the owning
package's durable approval policy. In particular, Molexp owns plan/approve/
resume tools; Molq is exposed to MolMCP only as read-only job snapshots.

## 7. CLI and configuration

The clean CLI is:

- `molmcp serve [--config molcrafts.json] [--transport ...]`
- `molmcp info`
- `molmcp search <query>`
- `molmcp explore <task>`
- `molmcp index [SOURCE...]`
- `molmcp registry validate <manifest>`
- `molmcp registry list`

`molcrafts.json` contains named sources, registry namespace mappings, cache
location, excludes, watcher settings, provider allowlist, and HTTP auth policy.
Explicit CLI flags override configuration. Environment variables are limited to
secrets and machine-specific cache/runtime paths.

Default transport is stdio and all data stays local. Streamable HTTP refuses to
start on a non-loopback address without configured authentication.

## 8. Implementation sequence

### Phase 1 — Contracts and registry

- Implement strict schema models, manifest loading/digesting, namespaced
  resolution, registry search, conflict detection, and fixtures.
- Remove the semantic-capability-to-executable conversion path.

### Phase 2 — Collection and context

- Introduce `CollectionIndex`, federated retrieval, `SearchHit`, and
  `ContextPack` over the existing Python graph as an intermediate backend.
- Replace the six old discovery tools with the four vNext tools.

### Phase 3 — Multi-language and cache rebuild

- Replace Rust/TypeScript stubs with Tree-sitter analyzers.
- Add Markdown/config analyzers, graph schema v4, complete cache identity,
  atomic writes, and freshness reporting.

### Phase 4 — CLI/config and provider ownership

- Replace the CLI, add `molcrafts.json`, automatic provider namespaces, and
  registry resources/prompts.
- Remove in-tree facades that depend on private Molexp/Molq APIs; package-owned
  adapters replace them.

### Phase 5 — Ecosystem manifests and integration

- First wave: molpy, molpack, molrs, molexp, molq, LAMMPS.
- Second wave: molnex, molvis, molcfg, mollog, molrec.
- Molexp consumes executable manifests directly and delegates long jobs to
  Molq. Symphony remains optional.

## 9. Test and acceptance plan

### Contract tests

- Strict manifest roundtrip and digest stability.
- Invalid IDs, unknown fields, missing side effects, malformed JSON Schema,
  cycles, conflicts, secret leakage, and unpinned execution all fail closed.
- A `DiscoveryHit` can never be coerced to `ExecutableCapabilityV1`.

### Analyzer/index tests

- Golden Python, Rust, TypeScript, Markdown, JSON, and TOML fixtures.
- Cross-file and cross-package edges with provenance assertions.
- Heuristic edges never affect ranking.
- Cache-profile isolation, concurrent writers, crash recovery, watcher pending
  state, and content-hash reconciliation.

### Retrieval/context tests

- English and Chinese MolCrafts task set covering single- and multi-package
  workflows.
- Correct capability appears in top 3 for the curated acceptance set.
- Full-collection search is the default and deterministic under partial source
  failure.
- Context budget, section priorities, source snippets, freshness, coverage,
  unresolved, and truncation are contract-tested.

### MCP/CLI tests

- Exactly four core tools with stable schemas and read-only annotations.
- stdio end-to-end calls and resource reads.
- Provider namespace collision prevention.
- HTTP non-loopback startup fails without auth.

### Ecosystem smoke tests

- Discover a Molpy structure builder.
- Resolve and describe `@molpack/pack` as one fixed workflow.
- Produce a Molexp-compatible executable catalog without signature inference.
- Observe a Molexp run and Molq job through read-only snapshots.
- Discover real Rust symbols in molpack and TypeScript symbols in molvis.

## 10. Completion criteria

The vNext refactor is complete when:

- old discovery/provider surfaces and tests have been removed or rewritten;
- all official first-wave packages are searchable in one collection;
- Rust and TypeScript public APIs are indexed;
- four-tool MCP and clean CLI pass contract and end-to-end tests;
- no inferred code symbol is executable;
- every response carries freshness and provenance;
- quality, formatting, and full test commands in `AGENTS.md` pass.
