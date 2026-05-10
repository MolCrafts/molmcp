# Deploy locally (stdio)

This guide covers the most common molmcp deployment: a local **stdio**
MCP server that an MCP client (Claude Code, Claude Desktop, Continue,
…) spawns as a subprocess each session. No HTTP, no auth, no
infrastructure — the client talks to molmcp over stdin/stdout the way a
shell pipes two processes together.

The first half of the page is **client-agnostic**: install the
dependencies, decide which packages to expose. The second half is the
**per-client wiring** — currently Claude Code; more clients land here
as we get to them.

---

## What `molmcp` actually serves

One server, one CLI (`molmcp` / `python -m molmcp`), three layers of
tooling — all on stdio by default:

| Layer | What the agent sees | When to use |
|-------|---------------------|-------------|
| **Introspection tools** (`IntrospectionProvider`) | Seven generic tools — `list_modules`, `list_symbols`, `get_source`, `get_docstring`, `get_signature`, `read_file`, `search_source` — pointed at any MolCrafts import root. | "Show me the source of `molpy.compute.RDF`. What does `molpack.pack` accept?" — the default loop. |
| **First-party Provider tools** | Stateful queries that introspection cannot answer: `molq_list_jobs`, `molexp_list_projects`, `molexp_list_runs`. | "What's running right now? What experiments are in this workspace?" |
| **Third-party Providers** | Whatever any installed package contributes via the `molmcp.providers` entry-point group, gated on the four-condition rule in [Provider design](../concepts/provider-design.md). | When a downstream package legitimately needs to expose a stateful query. |

There is no separate plugin-server CLI — historical `molmcp-molpy` /
`molmcp-molrs` / `molmcp-molpack` packages have been removed in favour
of the introspection-first loop.

## Prerequisites

- **Python ≥ 3.12** with the molmcp foundation:
  ```bash
  pip install molcrafts-molmcp
  ```
- One or more MolCrafts packages you want introspection over:
  ```bash
  pip install molcrafts-molpy molcrafts-molrs molcrafts-molpack
  ```
- For the first-party Provider tools, install the matching MolCrafts
  package — providers are lazy facades and skip themselves cleanly when
  their dep is missing:
  ```bash
  pip install molq      # enables MolqProvider
  pip install molexp    # enables MolexpProvider
  ```

!!! tip "Use a venv"

    Most clients spawn the server with whatever `python` is on `PATH`
    at the time of registration. A dedicated venv keeps the server's
    dependency tree predictable. With `uv`:
    ```bash
    uv venv && source .venv/bin/activate
    uv pip install molcrafts-molmcp molcrafts-molpy molq molexp
    ```

## What the first-party providers expose

Both register through the `molmcp.providers` entry-point group and are
auto-discovered when their upstream dep is importable. Each provider's
existence is justified against the four-condition rule — see
[Provider design](../concepts/provider-design.md).

=== "molq (`MolqProvider`)"

    Reads `~/.molq/jobs.db`. One read-only tool:

    - `molq_list_jobs` — local-DB job query, with optional cluster
      filter and a switch for including terminal-state records.

    Anything else (`molq_submit`, `molq_cancel`, `molq_cleanup`,
    `register_cluster`, `refresh_cluster`, `get_job_transitions`, …) is
    deliberately omitted — those mutate state and belong in the `molq`
    CLI itself, which the agent can invoke directly after introspecting
    `molq`.

=== "molexp (`MolexpProvider`)"

    Reads a `workspace.json`-rooted molexp workspace catalog. Two
    read-only tools:

    - `molexp_list_projects` — top-level workspace navigation.
    - `molexp_list_runs` — per-project / per-experiment run query,
      with a stable filter set and flat output.

    Per-run details (`get_run`, `get_metrics`, `get_asset_text`) are
    derivable from `molexp_list_runs` plus introspection over
    `molexp.workspace`.

The seven introspection tools cover every installed MolCrafts package
by default — see [Quickstart](quickstart.md#3-the-seven-introspection-tools).

---

## Wire it up

### Claude Code

Reference: [Claude Code MCP docs](https://docs.claude.com/en/docs/claude-code/overview).

#### One server for the whole MolCrafts environment

```bash
claude mcp add molcrafts -- python -m molmcp
```

What this command does:

- `claude mcp add molcrafts` — register an MCP server under the local
  Claude Code config with the friendly name `molcrafts`. This name
  becomes the `mcp__<name>__<tool>` prefix the agent sees.
- `--` — boundary between Claude Code's args and the spawn command.
  Everything after `--` is what Claude Code runs each session.
- `python -m molmcp` — the molmcp foundation. Auto-detects whichever of
  `{molpy, molpack, molrs, molq, molexp}` are installed and registers
  introspection over them. Auto-discovered Providers (`MolqProvider`,
  `MolexpProvider`, plus any third-party entry-point) register on top.

Verify:

```bash
claude mcp list
```

You should see:

```
molcrafts: python -m molmcp - ✓ Connected
```

#### Use it

Open a Claude Code session. Ask:

> What modules does molpy expose? Then show me the signature of
> `molpy.compute.RDF`.

Behind the scenes Claude calls:

- `mcp__molcrafts__list_modules` → every module under the registered
  import roots.
- `mcp__molcrafts__get_signature` with `symbol="molpy.compute.RDF"`.

The `mcp__<name>__<tool>` prefix is the `<name>` you passed to
`claude mcp add`.

#### Narrow to one package (optional)

If you want a server scoped to a single MolCrafts package — say, when
you're juggling multiple projects and want distinct MCP servers per
project root — pass `--import-root` explicitly:

```bash
claude mcp add molpy -- python -m molmcp --import-root molpy
```

The seven tools now operate over `molpy` only. Most users don't need
this; the default serves every installed package and the agent simply
filters by module prefix when it asks.

#### Removing a server

```bash
claude mcp remove molcrafts
```

To rewire (e.g. point at a different venv), remove and re-add.

#### Troubleshooting (Claude Code)

**"✗ Failed to connect"** — run the spawn command in a terminal to see
the traceback:

```bash
python -m molmcp
```

The server should print nothing and wait for stdin (because that's
where Claude Code would normally talk to it). `Ctrl+C` to exit. Common
causes: wrong Python on PATH, no MolCrafts packages installed in that
venv, `molcrafts-molmcp` missing.

**Tools not showing up after `claude mcp add`** — restart the Claude
Code session. Tool registration is read at session start.

**A first-party Provider isn't loaded** — molmcp logs auto-discovered
Providers at startup and *skips* (with a warning) any whose dep is
missing or whose runtime state isn't reachable. Check the logs by
running the spawn command interactively. Install the upstream package
(`pip install molq` / `pip install molexp`) and restart the client.

**"Tool name collision"** — happens if two servers expose tools under
the same name. The `<name>` you pass to `claude mcp add` is the prefix;
use distinct names per server.

### Other clients

Add `--transport stdio` (the default) and point your client at the
spawn command. The exact config-file format varies by client; the
[CLI reference](../reference/cli.md#wiring-into-claude-desktop) has a
worked Claude Desktop JSON example. Other clients (Continue, Cursor,
…) land here as we write them up.

---

## A worked example: pick the right RDF binning

Open your client and ask:

> I have an XYZ trajectory at `/tmp/water.xyz` in a 30 Å cubic box.
> Give me a Python snippet that computes the O–O RDF using molpy out
> to `r_max = 8 Å`. Confirm the relevant API exists first.

The agent will typically:

1. Call `mcp__molcrafts__list_symbols` with `module="molpy.compute"` to
   confirm `RDF` and `NeighborList` exist.
2. Call `mcp__molcrafts__get_signature` on
   `molpy.compute.RDF` and `molpy.compute.NeighborList` to learn the
   exact call shapes.
3. Write the snippet using the verified signatures.

That's the loop molmcp is built for: the agent verifies the API
against the live source before writing code, instead of guessing from
training data.

---

## What's next?

- **[CLI reference](../reference/cli.md)** — every flag the `molmcp`
  CLI accepts.
- **[Architecture](../concepts/architecture.md)** — how the
  introspection layer and the Provider layer compose.
- **[Provider design](../concepts/provider-design.md)** — the
  four-condition rule that decides which capabilities earn a tool slot
  vs. stay in introspection-driven scripts.
- **[Write a Provider](../guides/write-a-provider.md)** — author a
  Provider for your own MolCrafts package after checking it against
  the design contract.
- Want stdout logs from the server? molmcp keeps stdout silent because
  that's the MCP wire. Use `--transport streamable-http` and run the
  server in another terminal if you need to watch what it does.
