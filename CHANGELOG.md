# Changelog

All notable changes to molmcp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/MolCrafts/molmcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/MolCrafts/molmcp/releases/tag/v0.1.0
