# molmcp-molexp

MCP plugin exposing a workspace catalog reader for molexp projects.

Six read-only tools: `list_projects`, `list_experiments`, `list_runs`,
`get_run`, `get_metrics`, `get_asset_text`.

Workspace resolution order: constructor arg → `MOLEXP_WORKSPACE` env var
→ cwd detection.

## Run standalone

```bash
MOLEXP_WORKSPACE=/path/to/workspace \
  uv run --package molmcp-molexp molmcp-molexp --transport stdio
```

## Mount under a gateway

```python
from fastmcp import FastMCP
from molmcp_molexp.server import mcp as molexp_mcp

gateway = FastMCP("my-gateway")
gateway.mount(molexp_mcp, namespace="molexp")
```
