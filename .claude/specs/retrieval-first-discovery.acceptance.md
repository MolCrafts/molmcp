---
spec: retrieval-first-discovery
created: 2026-07-07
criteria:
  - id: ac-001
    summary: "read-lammps query ranks the real LAMMPS reader first"
    type: runtime
    pass_when: "For query 'read a lammps data file', find_capability returns LammpsDataReader or read_lammps_data at rank 1, and AcReader.read is not in the top 3."
    status: verified
    last_checked: 2026-07-07
  - id: ac-002
    summary: "ranking no longer consumes unfiltered graph-degree"
    type: runtime
    pass_when: "rank_signals for a node whose only incoming CALLS edges are HEURISTIC contributes 0 from the caller feature; the score is unchanged if those heuristic edges are removed."
    status: verified
    last_checked: 2026-07-07
  - id: ac-003
    summary: "class-instantiation (constructor) edge restored"
    type: runtime
    pass_when: "resolve emits a RESOLVED CALLS edge from read_lammps_data to LammpsDataReader; describe_symbol(read_lammps_data) shows a callee that is the LammpsDataReader class."
    status: verified
    last_checked: 2026-07-07
  - id: ac-004
    summary: "blind sink eliminated"
    type: runtime
    pass_when: "AcReader.read's resolved caller_count does not include cross-file .read() calls whose receiver type is unresolved (e.g. read_lammps_data is not counted as a caller of AcReader.read)."
    status: verified
    last_checked: 2026-07-07
  - id: ac-005
    summary: "call graph preserved as a provenance-labeled feature"
    type: runtime
    pass_when: "relations(callers) / relations(callees) still return results, and every returned edge carries a provenance field distinguishing RESOLVED from HEURISTIC."
    status: verified
    last_checked: 2026-07-07
  - id: ac-006
    summary: "ranking uses only retrieval-quality + reliable signals"
    type: code
    pass_when: "ranking.py's scoring references field-weighted lexical match, is_exported, examples, tests, kind prior, and (at most) resolved-only callers — no unfiltered incoming-edge count feeds the score."
    status: verified
    last_checked: 2026-07-07
  - id: ac-007
    summary: "optional lightweight-model relevance judge"
    type: runtime
    pass_when: "With ANTHROPIC_API_KEY set, scripts/eval_relevance.py runs a claude-haiku-4-5 judge over golden_queries.yaml and reports a mean relevance score; without the key it prints SKIP and exits 0. It is not part of the default CI gate."
    status: verified
    last_checked: 2026-07-07
  - id: ac-008
    summary: "call-graph-as-feature stance documented"
    type: docs
    pass_when: "CLAUDE.md (or .claude/notes/) states that the call graph is an optional evidence feature and has been removed from the ranking path."
    status: pending
out_of_scope:
  - "Semantic vector retrieval (local embedding + hybrid rerank)."
  - "Real receiver-type inference (Jedi / PyCG / SCIP)."
  - "Adopting stack-graphs / SCIP as the resolution substrate."
  - "Equivalent fixes for the ts/rust/cpp analyzers."
---

# Acceptance — retrieval-first-discovery

"Done" means: capability search returns the *right* API first, and it does so
because retrieval quality (not a corrupt call-graph degree count) drives the
ranking. The call graph survives as an explicitly optional, provenance-labeled
evidence feature that no longer influences ranking, and the two resolver
defects that produced the poisoned edges (lost constructor edge, blind
alphabetical sink) are fixed. A deterministic golden-set regression locks the
canary query in place; a lightweight-model judge is available but non-gating.

## AC-001 — read-lammps ranks the real reader first

The canary. Query text roughly "read a lammps data file / script". Expected
top-1 is `LammpsDataReader` or `read_lammps_data`; `AcReader.read` must not
appear in the top 3. Asserted deterministically in
`tests/discovery/test_golden_ranking.py` against a hermetic reader fixture
(`tests/discovery/golden_queries.py`) that reproduces the poison shape.
**Verified** — golden regression green (3 cases).

## AC-002 — ranking ignores unfiltered graph-degree

A node whose incoming CALLS edges are all HEURISTIC yields a resolved caller
count of 0, so the caller feature contributes nothing. **Verified** —
`tests/discovery/test_provenance_counts.py` (store filter + `query.caller_counts`
resolved-only).

## AC-003 — constructor edge restored

`read_lammps_data` instantiates `LammpsDataReader`; the resolver emits a
RESOLVED CALLS edge to the class node. **Verified** —
`test_receiver_resolution.py::test_constructor_call_resolves_to_class`.

## AC-004 — blind sink eliminated

Cross-file `.read()` calls with an uninferable receiver are left unresolved,
not attributed to the alphabetically-first `read` method. **Verified** —
`test_receiver_resolution.py::test_unresolved_receiver_not_sunk_to_alpha_first`.

## AC-005 — call graph preserved, labeled

`relations(callees)` still returns edges and each carries `provenance`.
**Verified** — `test_golden_ranking.py::test_relations_expose_provenance`.

## AC-006 — clean ranking signals

Static: `ranking.py` scores from field-weighted lexical position (bm25 column
weights in `graphstore.search`), is_exported, example/test coverage, kind
prior, and resolved-only callers. No unfiltered incoming-edge count reaches the
score. **Verified** — code inspection + janitor pass.

## AC-007 — optional lightweight-model judge

`scripts/eval_relevance.py` uses `claude-haiku-4-5`; gated on
`ANTHROPIC_API_KEY`, SKIP + exit 0 when absent, not in the CI gate. **Verified**
— the binding observable (SKIP path, exit 0, absent from `ci.yml`/pytest) was
executed; the keyed judge path is code-correct but not exercised here (no key
available in this environment).

## AC-008 — documented stance

`CLAUDE.md` records that the call graph is an optional evidence feature removed
from ranking, with type inference flagged as a future track. Written; `docs`
type, so owed to a human/`/mol:close --manual` verification rather than the
`/mol:impl` code/runtime path.
