---
title: molmcp
description: molmcp indexes a codebase into a queryable code graph, so an AI agent resolves the real API from real code instead of guessing.
hide:
  - navigation
  - toc
hero:
  title: molmcp
  description: "A read-only MCP server that turns source code into graph-backed discovery tools. Agents can find capabilities, inspect symbols, walk relations, see examples and tests, and verify every answer against a concrete source snapshot."
  install:
    label: Install
    command: pip install molcrafts-molmcp
  badges:
    - img: https://img.shields.io/pypi/v/molcrafts-molmcp
      href: https://pypi.org/project/molcrafts-molmcp/
      alt: PyPI version
    - img: https://img.shields.io/badge/python-3.12%2B-blue.svg
      href: https://pypi.org/project/molcrafts-molmcp/
      alt: Python 3.12+
    - img: https://img.shields.io/badge/license-BSD--3--Clause-blue.svg
      href: https://github.com/MolCrafts/molmcp/blob/master/LICENSE
      alt: License BSD-3-Clause
  actions:
    - label: Get started
      href: get-started/installation/
      style: primary
    - label: Discovery tools
      href: reference/cli/
    - label: Provider design
      href: concepts/provider-design/
---

<h1 class="molcrafts-sr-only">molmcp</h1>

<div class="molcrafts-manual-home" markdown>

<!-- ────────────────────────────────────────────────────────────
     FEATURES — direct product capabilities
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Features</span>

## Code discovery an agent can verify

molmcp gives an agent read-only tools backed by indexed source, not guessed
names. Every result carries the symbol, file, line, signature, related examples
or tests, and the exact source snapshot that produced it.

</div>

<div class="molcrafts-manual-grid molcrafts-manual-grid--cols-3">
  <a href="reference/cli/">
    <strong>Capability search</strong>
    <em>Describe a task in plain language and get ranked symbols with signatures, summaries, examples, tests, callers, and provenance.</em>
  </a>
  <a href="reference/cli/">
    <strong>Symbol inspection</strong>
    <em>Open one qualname and retrieve docstrings, signatures, source snippets, examples, tests, caller counts, and callee counts.</em>
  </a>
  <a href="reference/cli/">
    <strong>Graph relations</strong>
    <em>Walk callers, callees, subclasses, implementations, examples, tests, references, and impact from any indexed symbol.</em>
  </a>
  <a href="concepts/discovery/">
    <strong>Source outline</strong>
    <em>Map a package or repository into modules and symbols before deciding where to inspect more deeply.</em>
  </a>
  <a href="concepts/discovery/">
    <strong>Snapshot cache</strong>
    <em>Index installed packages, local paths, or GitHub repositories into content-addressed SQLite graphs with FTS5 search.</em>
  </a>
  <a href="concepts/provider-design/">
    <strong>Provider extension</strong>
    <em>Add curated read-only tools for live state that static source cannot answer, gated by a strict four-condition rule.</em>
  </a>
</div>

</section>

<!-- ────────────────────────────────────────────────────────────
     THE TOOLS — six graph operations
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">The tool surface</span>

## Six read-only MCP tools

Every tool is `readOnlyHint=True` and every response includes a `snapshot`
block, so agent actions remain inspectable and tied to a concrete revision.

</div>

<dl class="molcrafts-feature-matrix">
  <dt><code>find_capability</code></dt>
  <dd>Task description to ranked symbol matches. This is the primary entry point when the agent knows what it needs but not the API name.</dd>
  <dt><code>search_symbols</code></dt>
  <dd>Full-text search over indexed names, qualnames, and summaries.</dd>
  <dt><code>describe_symbol</code></dt>
  <dd>Full detail for one qualname: signature, docstring, examples, tests, caller/callee counts, and optional source.</dd>
  <dt><code>relations</code></dt>
  <dd>Graph walks from a symbol: callers, callees, subclasses, implementations, examples, tests, references, and impact.</dd>
  <dt><code>outline</code></dt>
  <dd>Package and module map for a source, useful when the agent needs the shape of a codebase first.</dd>
  <dt><code>refresh</code></dt>
  <dd>Force a fresh incremental re-index of a source.</dd>
</dl>

</section>

<!-- ────────────────────────────────────────────────────────────
     THE DEMO — a plain-language question answered from the graph
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Example</span>

## Ask in plain language, get back real symbols

An agent describes a task. molmcp answers from indexed code: real qualnames,
files and lines, examples that use the symbol, and tests that exercise it.
Names that do not resolve come back as structured errors.

</div>

```text
molmcp_find_capability("radial distribution function", source="pkg:molpy")

→ molpy.compute.rdf.RDF                    class   src/molpy/compute/rdf.py:14
    summary    Compute g(r) between two atom selections.
    signature  RDF(bins=100, r_max=None)
    examples   examples/rdf_basic.py                         (exemplifies)
    tests      tests/test_compute/test_rdf.py::test_rdf      (tests)
    callers    molpy.compute.__init__ · molpy.analysis.rdf_report   (calls)
    provenance resolved · fts_rank 0.91 · callers 2 · tests 1
```

</section>

<!-- ────────────────────────────────────────────────────────────
     INDEXED SOURCE MODEL
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Indexed source model</span>

## Nodes, edges, provenance, snapshots

molmcp parses source statically. Symbols become nodes; calls, imports,
inheritance, tests, examples, and capability tags become edges. Each edge records
whether it came from direct AST parsing, unique resolution, or a heuristic match.

</div>

<dl class="molcrafts-feature-matrix">
  <dt>21 node kinds</dt>
  <dd><code>package</code> · <code>module</code> · <code>class</code> · <code>function</code> · <code>method</code> · <code>property</code> · <code>field</code> · <code>constant</code> · <code>example</code> · <code>test</code> · <code>capability</code> · <code>convention</code> …</dd>
  <dt>15 edge kinds</dt>
  <dd><code>contains</code> · <code>calls</code> · <code>extends</code> · <code>imports</code> · <code>tests</code> · <code>exemplifies</code> · <code>provides_capability</code> · <code>governs</code> …</dd>
  <dt>Content-addressed snapshots</dt>
  <dd>Local sources are keyed by content hash; GitHub sources by resolved commit. A cached graph always points at exact source, never a floating branch name.</dd>
</dl>

```text
source spec ─▶ snapshot ─▶ extract symbols ─▶ resolve names ─▶ graph.db
 pkg:molpy      content      analyzers emit      calls/imports      SQLite +
 ./path         hash or      shared nodes        linked to defs     FTS5
 github:repo    commit
```

</section>

<!-- ────────────────────────────────────────────────────────────
     RUN IT — one command
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--compact" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Run it</span>

## One command, discovery online

`python -m molmcp` indexes the MolCrafts packages `molpy, molpack, molrs, molq,
molexp, molnex` from a local install when available and from GitHub otherwise.
It serves the six discovery tools over MCP stdio, plus each present package's
Provider.

</div>

```bash
pip install molcrafts-molmcp
python -m molmcp
# then, from another terminal:
claude mcp add molcrafts -- python -m molmcp
```

</section>

<!-- ────────────────────────────────────────────────────────────
     MANUAL INDEX
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Find your page</span>

## The manual, front to back

</div>

<nav class="molcrafts-manual-index" aria-label="Manual chapters">
  <a href="get-started/installation/">
    <span>01</span>
    <strong>Installation</strong>
    <em>Install molmcp and confirm the discovery tools come online.</em>
  </a>
  <a href="get-started/quickstart/">
    <span>02</span>
    <strong>Quickstart</strong>
    <em>Run the server, wire it into Claude Code, and call the six tools.</em>
  </a>
  <a href="concepts/discovery/">
    <span>03</span>
    <strong>Discovery engine</strong>
    <em>How the code graph is built, stored, queried, and refreshed.</em>
  </a>
  <a href="concepts/architecture/">
    <span>04</span>
    <strong>Architecture</strong>
    <em>How discovery, providers, and middleware compose into one server.</em>
  </a>
  <a href="concepts/provider-design/">
    <span>05</span>
    <strong>Provider design</strong>
    <em>The four-condition rule that gates every tool beyond the graph.</em>
  </a>
  <a href="guides/write-a-provider/">
    <span>06</span>
    <strong>Write a Provider</strong>
    <em>Add a stateful tool the discovery graph cannot answer on its own.</em>
  </a>
  <a href="reference/cli/">
    <span>07</span>
    <strong>Reference</strong>
    <em>The CLI and the full API surface.</em>
  </a>
</nav>

</section>

</div>
