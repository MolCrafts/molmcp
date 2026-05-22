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
  <a href="https://github.com/MolCrafts/molmcp/issues"><strong>Issues</strong></a>
</p>

---

## Why molmcp

The MolCrafts ecosystem ships many packages — `molpy`, `molcfg`, `molexp`, `molpack`, `mollog`, `molq`, `molrec`, `molvis` — and each of them benefits from being callable by an LLM agent. The hard part is **discovery**: an agent needs to find out what a codebase actually provides instead of guessing function, class, or tool names.

molmcp solves this with a **graph-based codebase capability discovery engine**. It statically indexes a repository into a code graph — symbols, signatures, docstrings, relationships, examples, and tests — and exposes that graph to agents over the Model Context Protocol.

It does two things:

1. Runs a **discovery engine** that indexes any codebase (a local path, an installed package, or — soon — a GitHub repository) into a snapshot-cached code graph, and answers structured queries against it.
2. Defines a **Provider** plugin contract for the narrow class of capabilities discovery cannot answer — stateful queries against local runtime state (a jobs DB, a workspace catalog) — under a single coordinated MCP server with shared security defaults.

molmcp core imports nothing from the MolCrafts packages. That's the point — it's pure infrastructure, and any codebase can be indexed without molmcp depending on it.

## Discovery, not guessing

The discovery engine is built so an agent **resolves capabilities from indexed code structure** rather than guessing names:

- It parses source with a per-language analyzer (Python today on the stdlib `ast` module; TypeScript, Rust, and C++ slot in behind the same `LanguageAnalyzer` interface) into a shared graph of nodes and edges.
- A two-phase pipeline — extraction then resolution — links calls, base classes, imports, tests, and docstring examples into a connected graph.
- The graph is stored as one SQLite database per **source snapshot**, keyed on a content hash (local) or commit SHA (GitHub) — never a branch name — so cached results are always tied to exact source.
- Every tool response carries a `snapshot` block, so an agent always knows which revision it is looking at.

## Discovery tools

When discovery sources are configured, molmcp exposes six composable, graph-backed tools (all read-only):

| Tool | Purpose |
|---|---|
| `molmcp_find_capability` | Primary tool — describe a task, get ranked symbol matches with signatures, examples, tests, and callers. |
| `molmcp_search_symbols` | Search indexed symbols by name, qualname, or summary. |
| `molmcp_describe_symbol` | Full detail for one symbol, optionally with source code. |
| `molmcp_relations` | Walk the graph from a symbol: callers, callees, implementers, subclasses, references, examples, tests, impact. |
| `molmcp_outline` | Map a source's packages/modules to their symbols — the "where do I look" tool. |
| `molmcp_refresh` | Force a fresh re-index of a source. |

## Provider plugin contract

Discovery answers most questions. For the rest — queries that depend on local runtime state no static analysis can recover — molmcp defines a **Provider** plugin contract. A Provider earns a tool slot only when **all four** conditions hold: stable signature, read-only/idempotent, every-session frequency, single-shot answer. See [`docs/concepts/provider-design.md`](docs/concepts/provider-design.md).

## Install

```bash
pip install molcrafts-molmcp
```

Requires Python ≥ 3.12. The PyPI distribution is `molcrafts-molmcp`; the import name is `molmcp`. The discovery engine adds no required runtime dependency — it uses the standard library.

## 60-second quickstart

Start an MCP server that indexes the installed MolCrafts packages:

```bash
python -m molmcp
```

molmcp auto-detects whichever of `{molpy, molpack, molrs, molq, molexp}` are importable and registers discovery over them. Point it anywhere with `--source`:

```bash
python -m molmcp --source pkg:molpy --source /path/to/a/repo
```

Wire it into Claude Code:

```bash
claude mcp add molcrafts -- python -m molmcp
```

Inspect the engine — or verify it works — without an MCP client:

```bash
molmcp discovery verify pkg:molpy   # self-check: counts, FTS, sample query
molmcp discovery index pkg:molpy
molmcp discovery outline pkg:molpy
molmcp discovery query pkg:molpy "radial distribution function"
```

`molmcp discovery verify` prints a health report and exits non-zero on
failure, so it doubles as a CI/setup check. See the
[discovery engine guide](https://molcrafts.github.io/molmcp/concepts/discovery/)
for the full verification walkthrough.

## Source specs

A discovery source is one of:

- `path/to/repo` — a local directory.
- `pkg:<name>` — an installed Python package (resolved by import name).
- `github:owner/repo[@ref]` — a GitHub repository (downloaded at a
  resolved commit; `GITHUB_TOKEN` is used when set).

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
                │  • DiscoveryProvider (molmcp_* )   │
                │  • Discovery engine core           │
                │      source → snapshot → extract   │
                │      → resolve → SQLite graph      │
                │  • Provider contract + discovery   │
                │  • PathSafety / ResponseLimit      │
                │  • Annotations validator           │
                └──────────────┬─────────────────────┘
                               │
            ┌──────────────────┼──────────────────────┐
            ▼                  ▼                      ▼
      MolqProvider      MolexpProvider     third-party providers
      (jobs.db)         (workspace.json     (entry-point group
                         catalog)            molmcp.providers)
```

The discovery engine core (`molmcp.discovery`) is MCP-free — it can be imported, scripted, and tested without FastMCP. Only `molmcp.discovery.provider` touches MCP.

## Adding domain tools

Before adding a Provider tool, check it against the four-condition rule in [`docs/concepts/provider-design.md`](docs/concepts/provider-design.md). If a tool earns a slot:

```python
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

## Status

Alpha. The discovery engine and Provider contract may shift before 1.0. Pin to `molcrafts-molmcp >= 0.2, < 0.3`.

## Contributing

```bash
git clone https://github.com/MolCrafts/molmcp.git
cd molmcp
pip install -e ".[dev]"
pytest
```

## License

BSD-3-Clause. See [LICENSE](LICENSE).

## Acknowledgements

molmcp is part of the [MolCrafts](https://github.com/MolCrafts) project. It implements the [Model Context Protocol](https://modelcontextprotocol.io/) using the [fastmcp](https://github.com/jlowin/fastmcp) server library.
