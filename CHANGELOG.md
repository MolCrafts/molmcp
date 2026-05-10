# Changelog

All notable changes to molmcp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-10

Initial release. molmcp is the MCP foundation for the MolCrafts ecosystem.

The design contract: **introspection-first**. Agents discover the
upstream MolCrafts API (molpy, molpack, molrs, molq, molexp) by reading
source through generic introspection tools, then call it from Python
or CLI. molmcp adds a Provider only when the answer depends on runtime
state introspection cannot see — see
`docs/concepts/provider-design.md` for the four-condition rule.

### Added

- `create_server()` factory: builds a configured MCP server with shared
  middleware and pluggable Providers. Auto-discovered providers that
  fail to register (missing runtime dep, version mismatch) are skipped
  with a warning instead of crashing the server.
- `IntrospectionProvider`: seven read-only tools (`list_modules`,
  `list_symbols`, `get_source`, `get_docstring`, `get_signature`,
  `read_file`, `search_source`) bound to a configurable list of import
  roots. The CLI defaults `--import-root` to whichever of
  `{molpy, molpack, molrs, molq, molexp}` are installed.
- `MolqProvider` (entry point `molq`): one read-only tool —
  `molq_list_jobs` (filterable read against the local jobs DB).
  Stateful queries only; submission/cancel/cleanup belong in the
  `molq` CLI per the four-condition rule.
- `MolexpProvider` (entry point `molexp`): two tools —
  `molexp_list_projects` and `molexp_list_runs`. Stateful queries only.
- `Provider` Protocol and `discover_providers()`: third-party plugin
  contract via the `molmcp.providers` entry point group.
- `PathSafetyMiddleware`: blocks `..` traversal and NUL bytes in
  path-shaped arguments.
- `ResponseLimitMiddleware`: caps tool responses at 256 KB by default
  with a truncation marker.
- `validate_tool_annotations()` / `MissingAnnotationsError`: refuses to
  start a server containing a tool without `readOnlyHint` or
  `destructiveHint`.
- `run_safe()` / `SubprocessResult`: hardened subprocess helper for
  Provider authors who shell out to external CLIs.
- `fence_untrusted()`: marks file contents as data, not instruction,
  when returning them to the LLM context.
- `molmcp` console script and `python -m molmcp` entry point with
  `stdio`, `streamable-http`, and `sse` transports.

[0.1.0]: https://github.com/MolCrafts/molmcp/releases/tag/v0.1.0
