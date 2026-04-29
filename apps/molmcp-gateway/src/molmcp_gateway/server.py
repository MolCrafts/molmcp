"""Gateway entry point that mounts every MolCrafts MCP plugin.

The gateway itself is a bare ``FastMCP`` — middleware (path safety,
response limit, annotation validation) is applied by each plugin in its
own ``server.py`` via ``molmcp.create_server``. Mounting twice would
run those middlewares twice on every request.

For online deployment (e.g., Horizon), the entry point is::

    apps/molmcp-gateway/src/molmcp_gateway/server.py:mcp
"""

from __future__ import annotations

from fastmcp import FastMCP

from molmcp_lammps.server import mcp as lammps_mcp
from molmcp_molexp.server import mcp as molexp_mcp
from molmcp_molpy.server import mcp as molpy_mcp

from molmcp_gateway.config import DEFAULT_NAME

mcp = FastMCP(DEFAULT_NAME)
mcp.mount(molpy_mcp, namespace="molpy")
mcp.mount(molexp_mcp, namespace="molexp")
mcp.mount(lammps_mcp, namespace="lammps")
