---
slug: env-auto-discovery-02-wire
created: 2026-07-20
depends_on: env-auto-discovery-01-discover
criteria:
  - id: ac-001
    summary: no-file default folds workspace plus discovered sources
    type: runtime
    evaluator_hint: "path: tests/test_config.py"
    pass_when: |
      With config.discover_sources monkeypatched to return two DiscoveredSource
      entries and no molcrafts.json in cwd, load_config() returns
      config.sources == {"workspace": <cwd-abspath>} merged with the two
      discovered name->spec entries (workspace always present), and
      config.discovery carries their identified_by signals. The extended
      tests/test_config.py:10 passes.
    status: verified
    last_checked: 2026-07-20
  - id: ac-002
    summary: explicit molcrafts.json is never augmented
    type: runtime
    evaluator_hint: "path: tests/test_config.py"
    pass_when: |
      With a molcrafts.json present, load_config(path) returns exactly the file's
      resolved sources with no discovered entries, config.discovery is None, and
      a call-counting monkeypatched discover_sources is invoked zero times. The
      extended tests/test_config.py:17 passes.
    status: verified
    last_checked: 2026-07-20
  - id: ac-003
    summary: discovered-name collisions are deterministically disambiguated
    type: runtime
    evaluator_hint: "path: tests/test_config.py"
    pass_when: |
      A test where discovered names collide with "workspace" or with each other
      passes: each colliding name gets a deterministic suffix, "workspace" still
      maps to cwd, and every resulting source name matches config._SOURCE_NAME_RE.
    status: verified
    last_checked: 2026-07-20
  - id: ac-004
    summary: bad locator fails closed out of load_config
    type: runtime
    evaluator_hint: "path: tests/test_config.py"
    pass_when: |
      When discover_sources raises ConfigurationError (unresolvable locator),
      load_config(env_locator=<bad>) propagates ConfigurationError and does not
      silently return a workspace-only config.
    status: verified
    last_checked: 2026-07-20
  - id: ac-005
    summary: _resolve_source_spec passes pkg:/github:/local: through unchanged
    type: code
    pass_when: |
      Static inspection of src/molmcp/config.py shows _resolve_source_spec returns
      the spec unchanged for the "pkg:", "github:", and "local:" prefixes (local:
      added to the passthrough tuple), while relative paths are still resolved to
      absolute paths.
    status: verified
    last_checked: 2026-07-20
  - id: ac-006
    summary: --env precedence flag > MOLMCP_ENV > None threads correct locator
    type: runtime
    evaluator_hint: "path: tests/test_cli_vnext.py"
    pass_when: |
      With discover_sources monkeypatched to capture its locator argument:
      running a CLI command with --env X passes X; with no flag but MOLMCP_ENV=Y
      passes Y; with neither passes None. tests/test_cli_vnext.py cases pass.
    status: verified
    last_checked: 2026-07-20
  - id: ac-007
    summary: CLI surfaces a bad locator as exit code 2
    type: runtime
    evaluator_hint: "path: tests/test_cli_vnext.py"
    pass_when: |
      cli.main([...,"--env",<unresolvable>]) returns 2 and writes a "molmcp:"-
      prefixed message to stderr via the existing error path.
    status: verified
    last_checked: 2026-07-20
  - id: ac-008
    summary: info and config_summary expose the EnvironmentReport diagnostics
    type: runtime
    evaluator_hint: "path: tests/test_runtime.py"
    pass_when: |
      build_collection(config).metadata["discovery"] and
      collection.info()["configuration"]["discovery"] and config_summary(config)
      each expose the environment path/site_paths, the discovered packages with
      their identified_by signals, and the skipped/excluded lists; config_summary
      contains no credential values. tests/test_runtime.py cases pass.
    status: verified
    last_checked: 2026-07-20
  - id: ac-009
    summary: direct resolve_pkg coverage for the pkg: spec path
    type: runtime
    evaluator_hint: "path: tests/discovery/test_local_source.py"
    pass_when: |
      A new direct unit test in tests/discovery/test_local_source.py resolves
      pkg:fixture_pkg to a Snapshot rooted at the package parent whose file
      rel_paths include the package name, and it passes.
    status: verified
    last_checked: 2026-07-20
  - id: ac-010
    summary: regression drives load_config end-to-end and info surfaces discovery
    type: runtime
    evaluator_hint: "path: regressions/env-auto-discovery-02-wire.py"
    pass_when: |
      Running `python regressions/env-auto-discovery-02-wire.py` builds a synthetic
      environment, drives load_config(None, env_locator=<synthetic>) through
      build_collection to collection.info(), asserts the discovered package appears
      as a source with its environment path and identified-by signal visible under
      info()["configuration"]["discovery"], and exits 0.
    status: verified
    last_checked: 2026-07-20
  - id: ac-011
    summary: full check and test suite pass
    type: runtime
    pass_when: |
      `uv run ruff check src tests && uv run ruff format --check src tests &&
      uv run pytest -v` exits 0.
    status: verified
    last_checked: 2026-07-20
---

# Acceptance criteria — env-auto-discovery-02-wire

"Done" means 01's `discover_sources` is wired into the app assembly so that,
with no molcrafts.json, `molmcp` indexes the workspace plus one source per
auto-discovered MolCrafts-family package from the selected environment — while an
explicit molcrafts.json stays byte-for-byte authoritative — and `molmcp info`
reports what was found and why.

## AC-001..004 — config no-file folding (runtime)
The no-file branch folds discovered specs onto an unconditional `workspace`
source, disambiguates name collisions deterministically, carries the diagnostics
dict, and fails closed on a bad locator. The molcrafts.json-present branch is
never augmented (discovery None, discover_sources uncalled).

## AC-005 — spec passthrough (code)
`_resolve_source_spec` gains `local:` passthrough so discovered `local:<abspath>`
specs round-trip unchanged; existing pkg:/github:/relative-path behavior is
preserved.

## AC-006..007 — CLI locator selection (runtime)
`--env` on the shared config argument, with precedence flag > `MOLMCP_ENV` >
None(self), threads the locator into `load_config`; the no-args MCP launch is
covered via the env var. A bad locator surfaces as exit 2 through the existing
CLI error path.

## AC-008 — diagnostics (runtime)
`build_collection` metadata, `collection.info()["configuration"]["discovery"]`,
and `config_summary` expose the environment path, discovered packages with
`identified_by` signals, and skipped/excluded — secret-free.

## AC-009 — resolve_pkg coverage (runtime)
Closes the flagged gap with a direct unit test proving `pkg:fixture_pkg` resolves
to a parent-rooted snapshot — the path self-env discovery relies on.

## AC-010 — regression (runtime)
The binding end-to-end check: a synthetic environment drives `load_config` →
`build_collection` → `info()` and confirms the discovered package, its
environment path, and its identified-by signal are visible. Kept `runtime`
(verified by `/mol:impl` at delivery); lives in this repo's `regressions/`.

## AC-011 — suite
Full ruff + pytest suite green.
