# Changelog

All notable changes to molmcp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] — 2026-05-11

### Added

- `LammpsProvider` — knowledge navigator over docs.lammps.org with
  13 read-only tools (`get_doc_index`, `get_command_doc`,
  `get_style_doc`, `get_howto_doc`, `plan_task`,
  `get_workflow_outline`, `parse_script`, `validate_script`,
  `explain_command`, `list_howtos`, `search_howtos`, `get_howto`,
  `explain_error`) over alias / howto / workflow tables. Pure
  functions: no `lmp` invocation, no network, no filesystem. Lives
  at `src/molmcp/providers/lammps/` and is auto-discovered via the
  `molmcp.providers` entry-point. Default doc version is configurable
  through the `LAMMPS_MCP_DEFAULT_VERSION` env var. LAMMPS is a C++
  binary with a DSL, so introspection cannot reach it — the
  four-condition rule in `docs/concepts/provider-design.md` permits a
  curated provider here.
- `MolpyProvider` — three read-only tools (`list_compute_ops`,
  `list_readers`, `inspect_structure`) over `molpy`. Catalog entries
  are **discovered at call-time** by walking `molpy.compute` for
  `Compute` subclasses and `molpy.io` for `DataReader` /
  `BaseTrajectoryReader` subclasses; signatures come from
  `inspect.signature(cls.__init__)` and summaries from
  `inspect.getdoc(cls)`. No hardcoded class lists in the provider —
  when molpy adds a new reader or compute op, it surfaces
  automatically. `inspect_structure(path, reader)` instantiates the
  named reader on a filesystem path and returns a frame summary.
- `MolpackProvider` — three read-only tools (`list_restraints`,
  `list_formats`, `inspect_script`) over `molpack`. `list_restraints`
  discovers `*Restraint` classes from the live `molpack` module
  (Protocol-based subclass check is unusable because the native pyo3
  restraints don't surface `f`/`fg` to Python — naming convention
  matches molpack's own `__init__.py`). `list_formats` is an explicit
  mirror of the `read_frame` / `write_frame` `match` arms in
  `molpack/src/script/io.rs`, with a `source` pointer in the tool
  response so agents can verify against the Rust source of truth.
  `inspect_script(path)` parses a Packmol-compatible `.inp` script via
  `molpack.load_script`.
- Provider test coverage expanded substantially: `test_molq.py` 7 →
  21 cases (helpers, register-time dep guard, store-dispatch),
  `test_molexp.py` 12 → 30 cases (status coercion, run-row enrichment
  including on-disk parameter fallback, workspace resolution
  branches, catalog-query kwargs forwarding, limit cap, empty-state),
  plus new `test_lammps.py` (62 cases), `test_molpy.py` (9 cases),
  `test_molpack.py` (9 cases). All helper tests run without the
  respective domain dep installed; only true integration tests skip
  when the dep is missing.

### Changed

- Unified the `molmcp.providers` package layout: every provider now
  lives in its own subpackage (`providers/<name>/__init__.py` +
  `providers/<name>/provider.py`). `MolqProvider` and `MolexpProvider`
  were promoted from single-file modules; their public import paths
  (`molmcp.providers.molq:MolqProvider`,
  `molmcp.providers.molexp:MolexpProvider`) and entry-point names are
  unchanged — the re-export from `__init__.py` keeps them resolving
  as before.

## [0.2.0] — 2026-05-10

Consolidation release. The uv-workspace experiment that shipped sibling
plugin packages (`molmcp-molpy`, `molmcp-molrs`, `molmcp-molpack`,
`molmcp-lammps`, `molmcp-molexp`, `molmcp-gateway`) is retired in
favour of a single `molcrafts-molmcp` package — domain capabilities
reach the agent through `IntrospectionProvider` over the upstream
MolCrafts packages, not through curated re-export plugins. See
`docs/concepts/provider-design.md` for the four-condition rule that
drives this.

### Changed

- **Breaking:** `MolqProvider` now exposes a single read-only tool,
  `molq_list_jobs`. The earlier `molq_queue` / `molq_submit` /
  `molq_cancel` / `molq_cleanup` surface is removed — those are
  mutating verbs better served by the `molq` CLI itself, and the
  underlying molq APIs they relied on (`Cluster.from_alias`,
  `Submitor.purge_db_records`) no longer exist on current molq.
- **Breaking:** the `molmcp-*` sibling packages are no longer
  published. Install upstream MolCrafts packages directly (e.g.
  `pip install molcrafts-molpy`) and rely on introspection.

### Removed

- `apps/molmcp-gateway/` and `packages/molmcp-{lammps,molexp,molpack,molpy,molrs}/`
  workspace tree.
- `docs/concepts/naming.md` (orphan; not part of molmcp's surface).

### Fixed

- CI matrix realigned to the single-package layout.
- Release workflow simplified to `uv build` → PyPI Trusted Publisher
  (OIDC); no API tokens stored.

## [0.1.0] — 2026-05-10

Initial release. molmcp is the MCP foundation for the MolCrafts ecosystem.

The design contract: **introspection-first**. Agents discover the
upstream MolCrafts API (molpy, molpack, molrs, molq, molexp) by reading
source through generic introspection tools, then call it from Python
or CLI. molmcp adds a Provider only when the answer depends on runtime
state introspection cannot see — see
`docs/concepts/provider-design.md` for the four-condition rule.

### Added

- `create_server()` factory, `IntrospectionProvider`, `MolqProvider`,
  `MolexpProvider`, `Provider` Protocol + `discover_providers()`,
  `PathSafetyMiddleware`, `ResponseLimitMiddleware`,
  `validate_tool_annotations()`, `run_safe()`, `fence_untrusted()`, the
  `molmcp` console script over stdio / streamable-http / sse.

[0.2.1]: https://github.com/MolCrafts/molmcp/releases/tag/v0.2.1
[0.2.0]: https://github.com/MolCrafts/molmcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/MolCrafts/molmcp/releases/tag/v0.1.0
