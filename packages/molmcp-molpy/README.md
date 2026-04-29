# molmcp-molpy

MCP plugin exposing molpy's read-only structure-file inspector.

Two tools:

- `list_readers` — enumerate the structure / trajectory readers
  `molpy.io` exposes, with file-extension hints.
- `inspect_structure` — open a single-frame structure file via
  `molpy.io` and return a summary (format, block names, atom/bond
  counts, metadata).

## Run standalone

```bash
uv run --package molmcp-molpy molmcp-molpy --transport stdio
```

## Mount under a gateway

```python
from fastmcp import FastMCP
from molmcp_molpy.server import mcp as molpy_mcp

gateway = FastMCP("my-gateway")
gateway.mount(molpy_mcp, namespace="molpy")
```
