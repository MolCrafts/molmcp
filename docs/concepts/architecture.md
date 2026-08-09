# Architecture

molmcp is multi-plane MCP infrastructure for MolCrafts. **Each MCP connection
serves exactly one plane** (product domain). Clients link planes on demand.

**Protocol alignment:** servers run on **FastMCP 4 / MCP SDK v2**, which speak
MCP **2026-07-28** (sessionless `server/discover`) while still serving older
handshake-era clients.

```
  MCP clients (Claude, Grok, …)
       │
       │  separate stdio (or HTTP) links — connect only what you need
       │
       ├── catalog     list_planes / route
       ├── molcrafts   packages / outline / open / search / compose
       ├── molvis      open / exec / poll_events / …
       ├── molq        list_jobs / submit_job / …
       └── molexp      list_projects / materialize_workspace / …
```

There is **no** parent server that mounts every provider under `molmcp`.

## Responsibilities

### 1. Plane runtime

`create_plane(plane_id)` builds one FastMCP server whose **name is the plane
id**. Tool names are **bare** (`open`, `list_projects`). Clients see
`molvis__open` / `molexp__list_projects`. Startup **rejects**
`molexp_list_projects` and any `molexp_molexp_*` double-prefix style.

### 2. Knowledge plane (`molcrafts`)

OKF-style pages over the discovery graph: packages → outline → open → compose.
Codegraph ranks are evidence only. Science methods are discovered here and
invoked elsewhere.

### 3. Catalog plane

Bootstrap only: which planes exist, and which to connect for a free-text task.
Does not run science.

### 4. Provider planes

`Provider` protocol + `molmcp.providers` entry points. Each provider is its own
plane. Four-condition tool rule still applies (stable signature, read-only
default, high frequency, single-shot). No upstream API mirror.

## Request flow (example: draw a molecule)

1. `catalog.route("draw dopamine")` → connect `molvis` (+ ideally `molcrafts`).
2. `molcrafts.search` / `open` → real molpy/molvis symbols.
3. `molvis.open` → browser session.
4. `molvis.exec` → agent-written Python (`parse_molecule`, `draw_frame`, …).

## What molmcp does not do

- Mega-server with every tool mounted.
- Hard-coded chemistry tools (`show_smiles`, `optimize`, …).
- Science-package imports outside provider planes.

## Read next

- [Provider design](provider-design.md)
- [Discovery engine](discovery.md)
- [MolVis workbench](../guides/molvis-workbench.md)
