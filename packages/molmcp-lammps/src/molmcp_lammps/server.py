"""Standalone FastMCP server for the LAMMPS knowledge-navigator plugin.

The default LAMMPS doc version (``stable`` / ``latest`` / ``release``)
is read from the ``LAMMPS_MCP_DEFAULT_VERSION`` env var by the provider
itself; this module just constructs the provider with no overrides so
the same instance works in both standalone and gateway-mounted modes.
"""

from __future__ import annotations

from molmcp import create_server

from .provider import LammpsProvider

mcp = create_server(
    name="molmcp-lammps",
    providers=[LammpsProvider()],
    discover_entry_points=False,
    import_roots=None,
)
