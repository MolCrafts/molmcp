---
slug: env-auto-discovery-01-discover
created: 2026-07-20
criteria:
  - id: ac-001
    summary: environment.py is an MCP-free app-layer module with no name allowlist
    type: code
    pass_when: |
      Static inspection of src/molmcp/environment.py shows it imports nothing
      from molmcp.cli, molmcp.runtime, molmcp.server, molmcp.discovery, or
      fastmcp, and contains no hardcoded list of MolCrafts package names
      (e.g. no literal {"molpy","molpack","molq","molexp","molrs","molvis"}).
    status: verified
    last_checked: 2026-07-20
  - id: ac-002
    summary: never imports or subprocesses the target environment
    type: code
    pass_when: |
      Static inspection of src/molmcp/environment.py shows no subprocess,
      os.system, runpy, or importlib.import_module of enumerated distributions;
      direct_url.json is read via Distribution.read_text and parsed as text/JSON,
      and family metadata is read only through importlib.metadata Distribution
      accessors.
    status: verified
    last_checked: 2026-07-20
  - id: ac-003
    summary: resolve_site_paths normalizes locators and fails closed on bad ones
    type: runtime
    evaluator_hint: "path: tests/test_environment.py"
    pass_when: |
      The locator-normalization tests in tests/test_environment.py pass:
      a site-packages dir, a posix venv root (lib/python*/site-packages), and a
      python executable each resolve to an existing site-packages path via pure
      path globbing, and a nonexistent or unresolvable locator raises
      ConfigurationError.
    status: verified
    last_checked: 2026-07-20
  - id: ac-004
    summary: family signals a/b/c fire, record identified_by, and skip fail-soft
    type: runtime
    evaluator_hint: "path: tests/test_environment.py"
    pass_when: |
      Tests in tests/test_environment.py pass showing: a dist declaring any
      molmcp.* entry-point group, a dist with the molcrafts keyword, and a dist
      whose direct_url.json has dir_info.editable == true are each emitted with
      the matching identified_by literal ("entry_point"/"keyword"/"editable");
      a dist matching no signal is not emitted; and a dist with malformed
      direct_url.json or metadata is skipped without aborting enumeration of the
      others.
    status: verified
    last_checked: 2026-07-20
  - id: ac-005
    summary: MOLMCP_DISCOVER +name/-name overrides include/exclude, PEP503-matched
    type: runtime
    evaluator_hint: "path: tests/test_environment.py"
    pass_when: |
      Tests in tests/test_environment.py pass showing MOLMCP_DISCOVER="+extra,-molpy"
      force-includes a signal-less dist (identified_by contains "override") and
      force-excludes a signal-matched dist (recorded in EnvironmentReport.excluded),
      with names compared under PEP 503 normalization.
    status: verified
    last_checked: 2026-07-20
  - id: ac-006
    summary: spec emission — pkg: for self, local:<pkg-dir> for foreign, not repo root
    type: runtime
    evaluator_hint: "path: tests/test_environment.py"
    pass_when: |
      Tests in tests/test_environment.py pass showing self env (locator=None)
      emits pkg:<top_level>; a foreign non-editable dist emits
      local:<site-packages>/<top_level>; a foreign editable dist emits local:
      pointing at the package directory (<checkout>/<pkg> or <checkout>/src/<pkg>),
      asserted to be the package dir and NOT the git repo root; every emitted spec
      is accepted by SourceResolver.resolve without raising.
    status: verified
    last_checked: 2026-07-20
  - id: ac-007
    summary: regression script reproduces discovered specs and identified-by signals
    type: runtime
    evaluator_hint: "path: regressions/env-auto-discovery-01-discover.py"
    pass_when: |
      Running `python regressions/env-auto-discovery-01-discover.py` builds the
      synthetic site-packages fixture (fake .dist-info dirs exercising signals a,
      b, c plus one non-family wheel), calls discover_sources on it, asserts the
      emitted DiscoveredSource specs and identified_by sets equal the fixture's
      documented reference values, and exits 0.
    status: verified
    last_checked: 2026-07-20
  - id: ac-008
    summary: public API carries Google-style docstrings
    type: code
    pass_when: |
      The module docstring and the docstrings of discover_sources,
      resolve_site_paths, DiscoveredSource, and EnvironmentReport in
      src/molmcp/environment.py are Google-style and document args, returns, and
      raises (including the ConfigurationError condition and the "never import or
      execute the target environment" guarantee).
    status: verified
    last_checked: 2026-07-20
  - id: ac-009
    summary: full check and test suite pass
    type: runtime
    pass_when: |
      `uv run ruff check src tests && uv run ruff format --check src tests &&
      uv run pytest -v` exits 0.
    status: verified
    last_checked: 2026-07-20
---

# Acceptance criteria — env-auto-discovery-01-discover

"Done" means `src/molmcp/environment.py` exists as a self-contained, MCP-free
policy module that, without importing or executing any target environment,
discovers MolCrafts-family packages and emits `pkg:` / `local:<abspath>` source
specs plus a diagnostics report — verified purely through its own unit tests and
one public-API regression, with nothing wired into config/cli/runtime yet.

## AC-001 / AC-002 — boundary & safety (static)
The module stays in the app layer (no MCP, no discovery, no cli/runtime imports),
carries no hardcoded package-name allowlist (explicit user constraint), and never
imports or subprocesses the target environment. `direct_url.json` and all family
metadata are read via `importlib.metadata` accessors and text parsing only.

## AC-003 — locator normalization (runtime)
`resolve_site_paths` maps a site-packages dir, a venv root, and a python
executable to existing site-packages paths by pure path globbing
(`lib/python*/site-packages` on posix, `Lib/site-packages` on windows), and is
fail-closed: a nonexistent/unresolvable locator raises `ConfigurationError`
(the `config.py` idiom, reused).

## AC-004 / AC-005 / AC-006 — identification, override, emission (runtime)
The three default signals (a: any `molmcp.*` entry-point group; b: `molcrafts`
keyword; c: PEP 610 `dir_info.editable == true`) fire, are recorded in
`identified_by` using pinned literals, and are fail-soft per dist. `MOLMCP_DISCOVER`
`+`/`-` overrides include/exclude under PEP 503 name matching. Emission produces
`pkg:<top_level>` for the self env and `local:<package-dir-abspath>` for foreign
envs — the package directory, explicitly not the git repo root — and every spec
is consumable by the unchanged `SourceResolver`.

## AC-007 — regression (runtime)
`regressions/env-auto-discovery-01-discover.py` is the binding end-to-end check:
against a synthetic site-packages fixture it reproduces the documented set of
emitted specs and identified-by signals and exits 0. Kept `runtime` (verified by
`/mol:impl` at delivery); it lives in this repo's `regressions/`, not an external
bench.

## AC-008 / AC-009 — docs & suite
Public API is documented Google-style (including the no-import/no-exec guarantee),
and the full ruff + pytest suite is green.
