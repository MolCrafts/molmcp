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
| **Discovery tools** (`DiscoveryProvider`) | Six graph-backed tools — `molmcp_find_capability`, `molmcp_search_symbols`, `molmcp_describe_symbol`, `molmcp_relations`, `molmcp_outline`, `molmcp_refresh` — over any indexed source. | "What does molpy provide for an RDF? Show me `molpy.compute.RDF`. What calls it?" — the default loop. |
| **First-party Provider tools** | The five in-tree providers' tools: molq's `molq_list_jobs`; molexp's `molexp_list_projects` / `molexp_list_runs` / `molexp_workspace_layout` / `molexp_check_layout`; molpy's `list_compute_ops` / `list_readers` / `inspect_structure`; molpack's `list_restraints` / `list_formats` / `inspect_script`; and LAMMPS's 13 doc-navigation tools (`get_command_doc`, `plan_task`, `explain_error`, …). | "What's running? What experiments are in this workspace? What can molpy compute? How do I write this LAMMPS command?" |
| **Third-party Providers** | Whatever any installed package contributes via the `molmcp.providers` entry-point group, gated on the four-condition rule in [Provider design](../concepts/provider-design.md). | When a downstream package legitimately needs to expose a stateful query. |

There is no separate plugin-server CLI — historical `molmcp-molpy` /
`molmcp-molrs` / `molmcp-molpack` packages have been removed in favour
of the discovery-first loop.

## Prerequisites

- **Python ≥ 3.12** with the molmcp foundation:
  ```bash
  pip install molcrafts-molmcp
  ```
- One or more MolCrafts packages you want discovery over:
  ```bash
  pip install molcrafts-molpy molcrafts-molrs molcrafts-molpack
  ```
- For the dep-backed Provider tools, install the matching MolCrafts
  package — those providers are lazy facades and skip themselves cleanly
  when their dep is missing (`LammpsProvider` has no dep and always
  loads):
  ```bash
  pip install molcrafts-molq      # enables MolqProvider
  pip install molcrafts-molexp    # enables MolexpProvider
  pip install molcrafts-molpy     # enables MolpyProvider
  pip install molcrafts-molpack   # enables MolpackProvider
  ```

!!! tip "Use a venv"

    Most clients spawn the server with whatever `python` is on `PATH`
    at the time of registration. A dedicated venv keeps the server's
    dependency tree predictable. With `uv`:
    ```bash
    uv venv && source .venv/bin/activate
    uv pip install molcrafts-molmcp molcrafts-molpy molcrafts-molq molcrafts-molexp
    ```

## What the first-party providers expose

The five in-tree providers register through the `molmcp.providers`
entry-point group. The dep-backed ones auto-discover when their upstream
dep is importable; `LammpsProvider` has no dep and always loads. Each
provider's existence is justified against the four-condition rule — see
[Provider design](../concepts/provider-design.md).

=== "molq (`MolqProvider`)"

    Reads `~/.molq/jobs.db`. One read-only tool:

    - `molq_list_jobs` — local-DB job query, with optional cluster
      filter and a switch for including terminal-state records.

    Anything else (`molq_submit`, `molq_cancel`, `molq_cleanup`,
    `register_cluster`, `refresh_cluster`, `get_job_transitions`, …) is
    deliberately omitted — those mutate state and belong in the `molq`
    CLI itself, which the agent can invoke directly after discovering
    `molq`'s API.

=== "molexp (`MolexpProvider`)"

    Navigation + **idempotent scaffold** over a `workspace.json`-rooted
    molexp workspace. **Not a science executor** — do not use these tools
    to run sweeps or plots; agent-written Python against the molexp /
    molplot APIs owns that path.

    Read-only:

    - `molexp_list_projects` — top-level workspace navigation.
    - `molexp_list_experiments` — experiments under a project.
    - `molexp_list_runs` — per-project / per-experiment run query,
      with a stable filter set and flat output.
    - `molexp_workspace_layout` — the frozen on-disk layout contract
      (tree + naming law + OKF concept model), no inputs.
    - `molexp_check_layout` — read-only lint of a directory against
      that contract.
    - `molexp_validate_workflow` — compile-only workflow source check
      (no task bodies run).

    Scaffold (idempotent create-or-get; does **not** execute science):

    - `molexp_materialize_workspace` — create/open a Workspace at a path.
    - `molexp_add_project` / `molexp_add_experiment` — create-or-get
      on slug.
    - `molexp_create_run` — seed a pending run with params only
      (`executed: false`; no `RunSet.execute`).

=== "molpy (`MolpyProvider`)"

    Runtime catalog over the live `molpy` module. Three read-only tools:

    - `list_compute_ops` — `molpy.compute.Compute` subclasses, walked
      at call-time (name, signature, docstring head).
    - `list_readers` — `molpy.io` `DataReader` / `BaseTrajectoryReader`
      subclasses, walked at call-time.
    - `inspect_structure(path, reader)` — run a named `molpy.io` reader
      on a file and return a small `Frame` summary.

=== "molpack (`MolpackProvider`)"

    Runtime catalog + `.inp` inspector over `molpack`. Three read-only
    tools:

    - `list_restraints` — `*Restraint` classes discovered in the live
      `molpack` module at call-time.
    - `list_formats` — the script loader's I/O formats, mirroring
      molpack's Rust `io.rs`.
    - `inspect_script(path)` — parse a Packmol-compatible `.inp` via
      `molpack.load_script` and summarise its targets.

=== "lammps (`LammpsProvider`)"

    A pure-function knowledge navigator over docs.lammps.org — no `lmp`
    invocation, no network, no filesystem, no upstream dep. 13 read-only
    tools: `get_doc_index`, `get_command_doc`, `get_style_doc`,
    `get_howto_doc`, `plan_task`, `get_workflow_outline`, `parse_script`,
    `validate_script`, `explain_command`, `list_howtos`, `search_howtos`,
    `get_howto`, `explain_error`. Default doc version is configurable via
    the `LAMMPS_MCP_DEFAULT_VERSION` env var.

The six discovery tools cover every installed MolCrafts package
by default — see [Quickstart](quickstart.md#3-the-six-discovery-tools).

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
- `python -m molmcp` — the molmcp foundation. Indexes the MolCrafts
  packages `{molpy, molpack, molrs, molq, molexp, molnex}` for
  graph-based discovery — from a local install when present, from GitHub
  otherwise. The in-tree Providers (`MolqProvider`, `MolexpProvider`,
  `LammpsProvider`, `MolpyProvider`, `MolpackProvider`) plus any
  third-party entry-point register on top.

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

> What does molpy provide for computing an RDF? Then show me the
> signature of `molpy.compute.RDF`.

Behind the scenes Claude calls:

- `mcp__molcrafts__molmcp_find_capability` → ranked symbol matches for
  the task across the indexed sources.
- `mcp__molcrafts__molmcp_describe_symbol` with
  `qualname="molpy.compute.RDF"`.

The `mcp__<name>__<tool>` prefix is the `<name>` you passed to
`claude mcp add`.

#### Narrow to one package (optional)

If you want a server scoped to a single MolCrafts package — say, when
you're juggling multiple projects and want distinct MCP servers per
project root — pass `--source` explicitly:

```bash
claude mcp add molpy -- python -m molmcp --source pkg:molpy
```

The discovery tools now operate over `molpy` only. Most users don't need
this; the default indexes every installed package and the agent passes a
`source` argument when it needs to scope a query.

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
(`pip install molcrafts-molq` / `pip install molcrafts-molexp`) and
restart the client.

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

1. Call `mcp__molcrafts__molmcp_find_capability` with the task to surface
   the relevant symbols — `RDF`, `NeighborList` — with their signatures
   and usage examples.
2. Call `mcp__molcrafts__molmcp_describe_symbol` on
   `molpy.compute.RDF` and `molpy.compute.NeighborList` to learn the
   exact call shapes.
3. Write the snippet using the verified signatures.

That's the loop molmcp is built for: the agent resolves the API from the
indexed code graph before writing code, instead of guessing from
training data.

---

## What's next?

- **[CLI reference](../reference/cli.md)** — every flag the `molmcp`
  CLI accepts.
- **[Architecture](../concepts/architecture.md)** — how the
  discovery layer and the Provider layer compose.
- **[Provider design](../concepts/provider-design.md)** — the
  four-condition rule that decides which capabilities earn a tool slot
  vs. stay in discovery-driven scripts.
- **[Write a Provider](../guides/write-a-provider.md)** — author a
  Provider for your own MolCrafts package after checking it against
  the design contract.
- Want stdout logs from the server? molmcp keeps stdout silent because
  that's the MCP wire. Use `--transport streamable-http` and run the
  server in another terminal if you need to watch what it does.
