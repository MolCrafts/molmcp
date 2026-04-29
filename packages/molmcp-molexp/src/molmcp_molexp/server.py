"""Standalone FastMCP server for the molexp plugin.

The workspace root is resolved lazily at tool-call time inside the
provider (constructor arg → ``MOLEXP_WORKSPACE`` env var → cwd
detection), so this module-level ``mcp`` works in deployments where the
workspace path is only known at runtime.
"""

from __future__ import annotations

from molmcp import create_server

from .provider import MolexpProvider

mcp = create_server(
    name="molmcp-molexp",
    providers=[MolexpProvider()],
    discover_entry_points=False,
    import_roots=None,
)
