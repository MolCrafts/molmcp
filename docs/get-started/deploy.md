# Deploy locally (stdio)

Local **stdio** MCP: the client spawns `molmcp serve <plane>` as a subprocess
per session. No HTTP, no shared mega-server — **one plane per connection**.

---

## What molmcp serves

| Plane | Command | What the agent sees |
|-------|---------|---------------------|
| **catalog** | `molmcp serve catalog` | `list_planes`, `route(task)` — bootstrap only |
| **molcrafts** | `molmcp serve molcrafts` | Knowledge pages: `packages`, `outline`, `open`, `search`, `compose`, … |
| **molvis** | `molmcp serve molvis` | Live stage session: `open`, `exec`, `poll_events`, … |
| **molq** | `molmcp serve molq` | Job store (+ opt-in submit/cancel when enabled) |
| **molexp** | `molmcp serve molexp` | Workspace layout / scaffold tools |

Connect only the planes the session needs. Tool ids are
`<plane>__<tool>` (MCP server name + bare tool name).

There is no parent `python -m molmcp` that mounts every provider under one
server name.

## Prerequisites

- **Python ≥ 3.12**
  ```bash
  pip install molcrafts-molmcp
  ```
- For the **molcrafts** knowledge plane, a `molcrafts.json` with
  `schema_version: "2"` and at least one source (see
  [Installation](installation.md)).
- Optional domain packages for provider planes:
  ```bash
  pip install molcrafts-molpy    # richer local graph + science in-agent
  pip install molcrafts-molq     # molq plane
  pip install molcrafts-molexp   # molexp plane
  # molvis plane: page host + molvis Python/bindings per that package’s docs
  ```

!!! tip "Use a venv"

    Clients spawn the server with whatever `python` / `molmcp` is on `PATH`.
    A dedicated venv keeps the tree predictable:

    ```bash
    uv venv && source .venv/bin/activate
    uv pip install molcrafts-molmcp molcrafts-molpy
    ```

## Multi-link client config

### Claude Code

```bash
claude mcp add catalog -- molmcp serve catalog
claude mcp add molcrafts -- molmcp serve molcrafts
claude mcp add molvis -- molmcp serve molvis   # optional
claude mcp list
```

### Generic JSON

```json
{
  "mcpServers": {
    "catalog": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/molmcp", "molmcp", "serve", "catalog"]
    },
    "molcrafts": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/molmcp", "molmcp", "serve", "molcrafts"]
    }
  }
}
```

## Recommended agent loop

1. `catalog.route("…")` → which planes to connect.
2. `molcrafts.packages` / `outline` / `open` → real APIs into context.
3. Call science from agent Python (or `molvis.exec` for a live canvas).
4. Never invent MCP tools that re-export molpy/molrs methods.

Full viewer dialogue: [MolVis workbench](../guides/molvis-workbench.md).

## HTTP (optional)

```bash
molmcp serve molcrafts --transport streamable-http --host 127.0.0.1 --port 8787
```

Non-loopback binds require `server.auth_token_env` in `molcrafts.json`. Prefer
stdio for local agents.

## Offline helpers

```bash
molmcp planes
molmcp route "submit a job"
molmcp search "Conformer"
molmcp index    # when configured
```

## Read next

- [Quickstart](quickstart.md)
- [Architecture](../concepts/architecture.md)
- [Provider design](../concepts/provider-design.md)
- [Security](../guides/security.md)
