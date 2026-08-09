# Quickstart

Stand up **on-demand multi-plane** MCP for MolCrafts: connect only the product
domains you need. There is no single process that mounts every tool.

## 1. List planes

```bash
pip install molcrafts-molmcp
molmcp planes
molmcp route "draw dopamine"
```

Built-in planes include `catalog` (routing) and `molcrafts` (knowledge pages).
Provider planes (`molvis`, `molq`, `molexp`, …) appear when their packages /
entry points are available.

## 2. Serve one plane per process

```bash
# Terminal A — bootstrap routing
molmcp serve catalog

# Terminal B — knowledge pages (needs at least one configured source)
molmcp serve molcrafts

# Terminal C — live viewer (optional)
molmcp serve molvis
```

Each process is one MCP server whose **name is the plane id**. Clients see
bare tool names under that server: `molcrafts__packages`, `molvis__open`,
`catalog__route`.

## 3. Connect from Claude Code (multi-link)

Register **one MCP entry per plane**:

```bash
claude mcp add catalog -- molmcp serve catalog
claude mcp add molcrafts -- molmcp serve molcrafts
# only when drawing:
claude mcp add molvis -- molmcp serve molvis
```

JSON shape (any client that supports multiple servers):

```json
{
  "mcpServers": {
    "catalog": {
      "command": "molmcp",
      "args": ["serve", "catalog"]
    },
    "molcrafts": {
      "command": "molmcp",
      "args": ["serve", "molcrafts"]
    }
  }
}
```

Use absolute paths / `uv run --directory …` if the client’s PATH is thin.

## 4. Knowledge plane tools

On **molcrafts**, the main path is hierarchical pages:

| Tool | Role |
|------|------|
| `packages` | L0 package directory — choose sources |
| `outline` | Module / symbol map for one source |
| `open` | Inject one symbol page (optional source body) |
| `search` / `suggest` | Index helpers (prefer after packages/outline) |
| `compose` | Budgeted multi-page pack for a task |
| `info` | Ops / health — not the primary discovery path |

Science methods are **discovered** here and **invoked** in agent Python or
inside `molvis` `exec` — they are never re-wrapped as MCP science tools.

## 5. HTTP instead of stdio

```bash
molmcp serve molcrafts --transport streamable-http --host 127.0.0.1 --port 8787
```

Non-loopback HTTP requires auth configuration — see [Deploy](deploy.md).

## What's next?

- **[Deploy](deploy.md)** — full local stdio layout and client wiring
- **[Architecture](../concepts/architecture.md)** — plane model
- **[MolVis workbench](../guides/molvis-workbench.md)** — open / exec / poll_events
- **[Write a Provider](../guides/write-a-provider.md)** — add a product plane
