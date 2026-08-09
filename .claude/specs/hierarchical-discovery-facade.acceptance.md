# Acceptance — hierarchical-discovery-facade

Binding contract for "done". Types: `behavior` | `api` | `test` | `docs`.

## Criteria

### AC-01 — L0 packages list is the catalog entry point

- **type**: `api`
- **given** a collection with at least one ok source and optionally one error source
- **when** `molcrafts_packages` (or Python `browse.packages`) is called
- **then** every configured source appears as a card with `name`, `status`, `spec`, `freshness`
- **and** ok sources include `summary` from the package node when present (`summary_source` set), else `summary: null` with an explicit reason
- **and** error sources remain listed with `status: error` and `error` text (never omitted)

### AC-02 — L1 outline is hierarchical and source-scoped

- **type**: `api`
- **given** an indexed source (fixture_pkg or live molpy)
- **when** `molcrafts_outline(source=…)` is called
- **then** the response lists modules/packages with `qualname`, `kind`, and `summary` when available
- **and** `path` narrows the tree (e.g. only modules under that path prefix)
- **and** calling outline without a valid `source` returns `ok: false` with a stable `code` (e.g. `SOURCE_REQUIRED` / `SOURCE_NOT_FOUND`)

### AC-03 — L3 open is usage-first exact ref

- **type**: `api`
- **given** a ref returned by search or outline-derived symbol
- **when** `molcrafts_open(ref=…)` is called
- **then** success payload includes signature and/or summary, plus `examples`, `tests`, and `coverage` counts
- **and** empty examples/tests are represented as empty lists with `coverage.examples == 0` (not omitted as if unknown)
- **and** unknown ref returns `ok: false`, `code: SYMBOL_NOT_FOUND`, and a hint pointing to packages → outline → search

### AC-04 — search supports scoped retrieval

- **type**: `api`
- **when** `molcrafts_search` is called with `source=` (and optionally `kind=` / path filter)
- **then** all hits are constrained to that source (and kind/path when provided)
- **and** unscoped search still works for backward compatibility

### AC-05 — progressive path is what instructions teach

- **type**: `docs`
- **when** server default `instructions` and README quickstart are read
- **then** the primary taught loop is packages → outline → open → compose (context injection)
- **and** search/suggest are documented as index helpers only, not the main path
- **and** instructions state that codegraph is an index and markdown/pages are the payload

### AC-05b — responses are context-injectable pages

- **type**: `api`
- **when** packages / outline / open succeed
- **then** each response includes a non-empty `markdown` field suitable for prompt injection (or equivalent narrative body)
- **and** ranking scores are never the sole content of a successful discovery response

### AC-06 — aliases preserve one-release compatibility

- **type**: `behavior`
- **when** a client calls `molcrafts_describe` or `molcrafts_usage` or `molcrafts_guide`
- **then** the call succeeds with the same semantic payload as `open` / `suggest` (no 404 / missing tool)
- **and** core tool list includes the new names (`packages`, `outline`, `open`)

### AC-07 — no molexp package menu required for facade correctness

- **type**: `behavior`
- **given** only molmcp facade + live inventory
- **when** an agent follows packages → outline on a packing-capable install
- **then** the packing package appears in packages() with a non-empty summary or an honest null summary
- **and** facade tests do not hardcode molexp-side package tables

### AC-08 — regression suite

- **type**: `test`
- **when** `uv run pytest tests/test_browse.py tests/test_mcp_vnext.py tests/test_guide.py -q` (or project equivalent)
- **then** all pass
- **and** a test asserts the hierarchical tool set membership

## Non-criteria (explicitly not required for done)

- Every symbol has examples/tests.
- Registry executable_count > 0.
- Fixing upstream index errors for molpack/molrs (only visibility required).
- molexp plan e2e green (follow-up).
