"""Standalone FastMCP server for the molpy plugin."""

from __future__ import annotations

from molmcp import create_server

from .provider import MolPyProvider

mcp = create_server(
    name="molmcp-molpy",
    providers=[MolPyProvider()],
    discover_entry_points=False,
    import_roots=None,
)
