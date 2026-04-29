# molmcp-gateway

Aggregates the MolCrafts MCP plugins behind one endpoint via FastMCP's
`mount(...)`. Three plugins are mounted by default:

- `molpy`  → namespace `molpy`
- `molexp` → namespace `molexp`
- `lammps` → namespace `lammps`

The gateway can also expose source-introspection tools via an
`introspection` namespace; pass `--import-root <package>` (repeatable)
to add more, or `--no-introspection` to disable.

## Run

```bash
uv run --package molmcp-gateway molmcp-gateway --transport stdio
uv run --package molmcp-gateway molmcp-gateway \
  --transport streamable-http --host 0.0.0.0 --port 8787
```

## Online deployment

The deployment entry point is:

```
apps/molmcp-gateway/src/molmcp_gateway/server.py:mcp
```

Middleware (path safety, response limit, annotation validation) is
applied by each plugin in its own `server.py` via
`molmcp.create_server`, so the gateway's mounted graph already enforces
those guardrails.
