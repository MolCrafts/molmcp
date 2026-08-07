---
title: molmcp
description: Multi-plane MCP for MolCrafts — one product domain per connection, knowledge pages on demand, no mega-server.
hide:
  - navigation
  - toc
hero:
  kicker: molmcp Manual
  title: molmcp
  description: "Multi-plane, on-demand MCP for MolCrafts. Connect only the planes you need — catalog routing, molcrafts knowledge pages, molvis live sessions, molq jobs, molexp workspaces. Science APIs stay in code; agents discover them, then call them elsewhere."
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
    - label: Architecture
      href: concepts/architecture/
    - label: MolVis workbench
      href: guides/molvis-workbench/
---

<h1 class="molcrafts-sr-only">molmcp</h1>

<div class="molcrafts-manual-home" markdown>

<!-- ────────────────────────────────────────────────────────────
     FEATURES — direct product capabilities
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Features</span>

## One plane per connection

There is **no** mega-server that mounts every tool under `molmcp`. Clients
link planes on demand. Tool ids look like `molvis__open` or
`molcrafts__packages` — server name plus bare tool.

</div>

<div class="molcrafts-manual-grid molcrafts-manual-grid--cols-3">
  <a href="concepts/architecture/">
    <strong>catalog</strong>
    <em>Bootstrap only: list_planes and route(task) so the agent knows which product planes to connect.</em>
  </a>
  <a href="concepts/discovery/">
    <strong>molcrafts</strong>
    <em>OKF-style knowledge pages — packages → outline → open → search / compose — over a content-addressed code graph.</em>
  </a>
  <a href="guides/molvis-workbench/">
    <strong>molvis</strong>
    <em>Live viewer session: open a browser stage, exec Python, poll human selection events, redraw.</em>
  </a>
  <a href="concepts/provider-design/">
    <strong>molq / molexp</strong>
    <em>Job store and experiment workspace planes — each its own connection, gated by the four-condition rule.</em>
  </a>
  <a href="concepts/discovery/">
    <strong>Snapshot cache</strong>
    <em>Index installed packages, local paths, or GitHub repos into SQLite graphs with FTS5; every answer carries a snapshot.</em>
  </a>
  <a href="concepts/provider-design/">
    <strong>No invented science tools</strong>
    <em>Science APIs stay in molpy/molrs/… Agents discover them on molcrafts, then call them in agent Python or molvis exec.</em>
  </a>
</div>

</section>

<!-- ────────────────────────────────────────────────────────────
     THE TOOLS — six graph operations
     ──────────────────────────────────────────────────────────── -->

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">The molcrafts plane</span>

## Knowledge pages, not a tool mega-menu

On the **molcrafts** plane, tools are bare names (`packages`, `outline`,
`open`, …). Clients see `molcrafts__packages`. Every page-style response is
meant to be **injected into context** — not skimmed as a search hit list.

</div>

<dl class="molcrafts-feature-matrix">
  <dt><code>packages</code></dt>
  <dd>L0 directory of indexed packages and summaries — choose sources yourself.</dd>
  <dt><code>outline</code></dt>
  <dd>Module / symbol map for one source before you dive deeper.</dd>
  <dt><code>open</code></dt>
  <dd>Inject one symbol page (signature, docstring, examples, tests, optional source).</dd>
  <dt><code>search</code> / <code>suggest</code></dt>
  <dd>Index helpers — prefer after packages/outline, with an explicit <code>source=</code> when possible.</dd>
  <dt><code>compose</code></dt>
  <dd>Budgeted multi-page pack for a task (packages + suggest + open pages).</dd>
  <dt><code>info</code></dt>
  <dd>Ops / health view of sources and registry — not the main discovery path.</dd>
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
# catalog plane — which connections do I need?
catalog.route("compute an RDF in molpy")
→ connect molcrafts (knowledge) …

# molcrafts plane — inject real API pages
molcrafts.packages()                    # pick source "molpy"
molcrafts.search("RDF", source="molpy")
molcrafts.open("molpy.compute.rdf.RDF")
→ signature, docstring, examples, tests, snapshot
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

## One process per plane

Install once, then serve **only** the planes your client should see. Use
`molmcp planes` / `molmcp route "…"` to discover the catalog.

</div>

```bash
pip install molcrafts-molmcp
molmcp planes
molmcp serve catalog          # list_planes / route
molmcp serve molcrafts        # knowledge pages (needs at least one configured source)
molmcp serve molvis           # live viewer session
# Claude Code — one MCP entry per plane you connect:
#   claude mcp add catalog -- molmcp serve catalog
#   claude mcp add molcrafts -- molmcp serve molcrafts
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
    <em>Install molmcp and list connectable planes.</em>
  </a>
  <a href="get-started/quickstart/">
    <span>02</span>
    <strong>Quickstart</strong>
    <em>Serve catalog + molcrafts, wire multi-link MCP clients.</em>
  </a>
  <a href="concepts/architecture/">
    <span>03</span>
    <strong>Architecture</strong>
    <em>One plane per connection — catalog, knowledge, providers.</em>
  </a>
  <a href="concepts/discovery/">
    <span>04</span>
    <strong>Discovery engine</strong>
    <em>How the code graph is built, stored, and queried.</em>
  </a>
  <a href="guides/molvis-workbench/">
    <span>05</span>
    <strong>MolVis workbench</strong>
    <em>open → exec → poll_events loop for a live stage.</em>
  </a>
  <a href="concepts/provider-design/">
    <span>06</span>
    <strong>Provider design</strong>
    <em>Four-condition rule for every tool beyond knowledge pages.</em>
  </a>
  <a href="reference/cli/">
    <span>07</span>
    <strong>Reference</strong>
    <em>CLI and plane API surface.</em>
  </a>
</nav>

</section>

</div>
