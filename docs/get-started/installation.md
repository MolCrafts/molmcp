# Installation

molmcp is published on PyPI as **`molcrafts-molmcp`** and requires Python ≥ 3.12.
The import name is `molmcp`.

## With pip

```bash
pip install molcrafts-molmcp
```

## With uv

```bash
uv add --prerelease=allow molcrafts-molmcp
```

!!! note "Why the flag"

    molmcp requires **FastMCP 4** for MCP 2026-07-28, and FastMCP 4 is still
    in beta — PyPI's 4.x line is `4.0.0b2` with no final release yet. pip
    installs it without ceremony, but uv does not enable pre-releases for a
    dependency of a dependency, so it reports:

    ```
    Because only fastmcp<4.0.0b1 is available and molcrafts-molmcp
    depends on fastmcp>=4.0.0b1 ... cannot be used.
    ```

    Pinning an exact `==4.0.0b2` does not help — uv refuses that for the same
    reason. FastMCP 3.x is not an alternative: it speaks the older protocol,
    and molmcp's planes are built on the new one.

    The flag stops being necessary the day FastMCP 4.0.0 ships.

## What gets installed

The base install is infrastructure only: the multi-plane MCP runtime, knowledge
index, and CLI. Domain packages (molpy, molvis, molq, …) stay optional — install
them when you need a provider plane or richer local discovery.

## Optional extras

| Extra | Purpose | Command |
|-------|---------|---------|
| `dev` | pytest + ruff for the test suite and linting | `pip install "molcrafts-molmcp[dev]"` |
| `docs` | local preview of this documentation site | `pip install "molcrafts-molmcp[docs]"` |

Docs pin: `zensical>=0.0.53` and `molcrafts-zensical-theme>=0.2.5`.

## Verify the install

```bash
python -c "import molmcp; print(molmcp.__version__)"
molmcp planes
molmcp --help
```

`molmcp planes` lists connectable product domains. Each plane is a **separate**
MCP process (`molmcp serve <plane>`).

## Editable install (contributors)

```bash
git clone https://github.com/MolCrafts/molmcp.git
cd molmcp
uv sync --extra dev
uv run pytest -v
```

## Settings

Configuration lives in `~/.molmcp/settings.json` and is edited through the
CLI. There are no environment variables — `molmcp config list` is the whole
truth, which a variable that exists in one shell could never be.

```bash
molmcp config list
molmcp config set sources.molpy pkg:molpy
```

A project may add `.molmcp/settings.json` (checked in) and
`.molmcp/settings.local.json` (untracked). They layer over the user file in
that order. Writes target the user file unless `--project` or `--local` is
given: a plane server inherits its working directory from whichever MCP client
launched it, so project scope has to be asked for.

### What gets indexed

Installed MolCrafts distributions are discovered automatically — a package
qualifies by declaring a `molmcp.*` entry point or the `molcrafts` keyword, so
your dependencies are never dragged in.

The working directory is **not** a source unless you say so. It used to be
unconditionally, which meant an unconfigured install indexed whatever it was
started next to; one real install had accumulated two unrelated repositories,
a monorepo root, and a pile of temp directories that way.

```bash
molmcp config set indexWorkspace true --project   # index this repo as well
molmcp config set sources.atomiverse pkg:atomiverse
```

### Keys

| Key | Meaning |
|-----|---------|
| `sources` | Extra sources, `name → spec` (`pkg:`, `local:`, `github:`, or a path) |
| `indexWorkspace` | Also index the working directory (default `false`) |
| `knowledgeScope` | Narrow which indexed sources `packages` / `outline` / `open` surface |
| `excludes` | Extra ignore globs for the file walk |
| `watch` | Re-index local sources on change (default `true`) |
| `cacheDir` | Where the index lives (default `~/.cache/molmcp/discovery`) |
| `maxCacheBytes` | Ceiling on the code index (default 512 MB) |
| `maxCacheAgeDays` | Retention window for extraction payloads (default 30) |
| `pythonEnv` | Environment to discover from: a venv root, a python, or a site-packages dir |
| `discoverInclude` / `discoverExclude` | Force a distribution in or out of auto-discovery |
| `molexp.workspace` | Default molexp workspace path |
| `molq.database` | Override the molq job database |

Unknown keys are rejected. A mistyped `indexWorkspaces` that quietly does
nothing is worse than one that says so.

### `molcrafts.json`

Still accepted with an explicit `--config PATH`, but no longer picked up from
the working directory — that was the same accident-of-cwd the workspace source
was.

## Next steps

- **[Quickstart](quickstart.md)** — serve catalog + molcrafts and wire a client
- **[Architecture](../concepts/architecture.md)** — one plane per connection
- **[Deploy](deploy.md)** — multi-link stdio layout for Claude Code
