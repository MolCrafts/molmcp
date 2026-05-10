<h1 align="center">molmcp</h1>

<p align="center">
  <strong>The MCP foundation for the MolCrafts ecosystem</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/molcrafts-molmcp/"><img alt="PyPI" src="https://img.shields.io/pypi/v/molcrafts-molmcp?logo=python&logoColor=white&label=PyPI"></a>
  <a href="https://pypi.org/project/molcrafts-molmcp/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/molcrafts-molmcp.svg"></a>
  <a href="https://github.com/MolCrafts/molmcp/blob/master/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-BSD--3--Clause-blue"></a>
  <a href="https://github.com/MolCrafts/molmcp/actions"><img alt="CI" src="https://github.com/MolCrafts/molmcp/actions/workflows/ci.yml/badge.svg"></a>
</p>

<p align="center">
  <a href="https://molcrafts.github.io/molmcp/"><strong>Documentation</strong></a>
  &middot;
  <a href="https://molcrafts.github.io/molmcp/get-started/quickstart/"><strong>Quickstart</strong></a>
  &middot;
  <a href="https://molcrafts.github.io/molmcp/concepts/provider-design/"><strong>Provider design</strong></a>
  &middot;
  <a href="https://github.com/MolCrafts/molmcp/issues"><strong>Issues</strong></a>
</p>

---

## Why molmcp

The MolCrafts ecosystem ships many packages — `molpy`, `molcfg`, `molexp`, `molpack`, `mollog`, `molq`, `molrec`, `molvis` — and each of them benefits from being callable by an LLM agent. Without coordination, every package would have to author its own MCP server, redo the same source-introspection plumbing, redo the same security defaults, redo the same plugin wiring. molmcp is the layer that the MolCrafts packages share so they don't have to.

It does two things:

1. Exposes seven read-only **source-introspection tools** for any MolCrafts package, so an agent can ask "what does `molpy.core.atomistic` contain?" and get an exact answer from the live source.
2. Defines a **Provider** plugin contract for the narrow class of capabilities introspection cannot answer — stateful queries against local runtime state (a jobs DB, a workspace catalog) — under a single coordinated MCP server with shared security defaults.

molmcp itself imports nothing from the MolCrafts packages. That's the point — it's pure infrastructure, and any MolCrafts package can adopt it without dragging in the others.

## Design contract: introspection-first

molmcp is **not** a tool-registration mirror of upstream packages. The primary
mechanism for an agent to use a MolCrafts package is introspection: read the
source via `IntrospectionProvider`, then call the API from a Python snippet or
the package's CLI. A Provider earns a slot only when **all four** conditions
hold: stable signature, read-only/idempotent, every-session frequency,
single-shot answer — *and* the answer depends on runtime state introspection
cannot see. Everything else is a 3-line introspection script.

See [`docs/concepts/provider-design.md`](docs/concepts/provider-design.md) for
the full rule and the list of capabilities that were deliberately *not*
shipped.

## Features

- **Seven introspection tools** — `list_modules`, `list_symbols`, `get_source`, `get_docstring`, `get_signature`, `read_file`, `search_source` — pointed at any MolCrafts import root.
- **Two first-party providers** for stateful queries:
  - `MolqProvider` — `molq_list_jobs` (reads `~/.molq/jobs.db`).
  - `MolexpProvider` — `molexp_list_projects`, `molexp_list_runs` (reads a `workspace.json` catalog).
- **Provider plugin contract** — third-party MolCrafts packages contribute their own stateful-query tools via a `Provider` class plus an entry point. Auto-discovered, namespaced, version-able.
- **Security middleware** that's on by default — path-traversal guard, response-size cap (256 KB), and a startup-time check that refuses to serve any tool missing a `readOnlyHint`/`destructiveHint` annotation.
- **`run_safe` helper** — for Provider authors who shell out to external CLIs (Packmol, LAMMPS, AmberTools): forced list args, no `shell=True`, mandatory timeout.
- **Three transports** — `stdio`, `streamable-http`, `sse`.

## Install

```bash
pip install molcrafts-molmcp
```

Requires Python ≥ 3.12. The PyPI distribution is `molcrafts-molmcp`; the import name is `molmcp`.

## 60-second quickstart

Expose the installed MolCrafts packages as a set of MCP introspection tools:

```bash
python -m molmcp
```

molmcp auto-detects whichever of `{molpy, molpack, molrs, molq, molexp}` are
importable in the active environment and registers introspection over them.
Auto-discovered providers (`MolqProvider`, `MolexpProvider`, plus any
third-party entry point) load on top.

Wire it into Claude Code:

```bash
claude mcp add molcrafts -- python -m molmcp
```

The agent now has `mcp__molmcp__list_modules`, `mcp__molmcp__get_source`,
plus `molq_list_jobs` / `molexp_list_projects` etc. for whichever first-party
providers register successfully against the user's environment.

## Adding domain tools (for MolCrafts packages)

Before adding a tool, check it against the four-condition rule in
[`docs/concepts/provider-design.md`](docs/concepts/provider-design.md). Most
ideas don't pass — and if introspection plus a 3-line script can answer the
question, that's the right answer.

If a tool *does* earn a slot:

```python
# in a sibling package, e.g. src/molpack_mcp/__init__.py
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

class MolpackProvider:
    name = "molpack"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def list_pack_targets(workdir: str) -> list[dict]:
            """Return the in-progress pack targets cached under workdir."""
            from molpack import workspace
            return [t.to_dict() for t in workspace.scan(workdir).targets]
```

Declare the entry point in the package's `pyproject.toml`:

```toml
[project.entry-points."molmcp.providers"]
molpack = "molpack_mcp:MolpackProvider"
```

`python -m molmcp` discovers it automatically.

## Architecture

```
                ┌────────────────────────────────────┐
                │  MCP clients                       │
                │  (Claude Code, Claude Desktop, …)  │
                └──────────────┬─────────────────────┘
                               │   stdio / http / sse
                               ▼
                ┌────────────────────────────────────┐
                │  molmcp                            │
                │  • IntrospectionProvider           │
                │  • Provider contract + discovery   │
                │  • PathSafety / ResponseLimit      │
                │  • Annotations validator           │
                │  • run_safe / fence_untrusted      │
                └──────────────┬─────────────────────┘
                               │
            ┌──────────────────┼──────────────────────┐
            ▼                  ▼                      ▼
      MolqProvider      MolexpProvider     third-party providers
      (jobs.db)         (workspace.json     (entry-point group
                         catalog)            molmcp.providers)
```

molmcp itself is a single Python package — no MolCrafts package depends on any
other through it. First-party providers ship in-tree and are entry-point
discovered like any third-party Provider.

## Documentation

Full documentation lives at **[molcrafts.github.io/molmcp](https://molcrafts.github.io/molmcp/)**:

- [Installation & quickstart](https://molcrafts.github.io/molmcp/get-started/installation/)
- [Architecture](https://molcrafts.github.io/molmcp/concepts/architecture/)
- [Provider design contract](https://molcrafts.github.io/molmcp/concepts/provider-design/)
- [Writing a Provider](https://molcrafts.github.io/molmcp/guides/write-a-provider/)
- [Security model](https://molcrafts.github.io/molmcp/guides/security/)
- [CLI reference](https://molcrafts.github.io/molmcp/reference/cli/)

To preview the docs locally:

```bash
pip install "molcrafts-molmcp[docs]"
zensical serve
```

## Status

Alpha. The Provider contract and middleware surface may shift before 1.0. Pin to `molcrafts-molmcp >= 0.1, < 0.2`.

## Contributing

```bash
git clone https://github.com/MolCrafts/molmcp.git
cd molmcp
pip install -e ".[dev]"
pytest
```

## Releasing

1. Bump `version` in `pyproject.toml` and `__version__` in `src/molmcp/__init__.py`.
2. Update `CHANGELOG.md`.
3. `git tag v<X.Y.Z> && git push origin v<X.Y.Z>`.

The tag push fires `release.yml`, which builds and publishes to PyPI via [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) OIDC.

## License

BSD-3-Clause. See [LICENSE](LICENSE).

## Acknowledgements

molmcp is part of the [MolCrafts](https://github.com/MolCrafts) project. It implements the [Model Context Protocol](https://modelcontextprotocol.io/) using the [fastmcp](https://github.com/jlowin/fastmcp) server library.
