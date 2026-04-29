"""Static configuration for the molmcp gateway."""

from __future__ import annotations

DEFAULT_NAME = "molmcp-gateway"

DEFAULT_IMPORT_ROOTS: tuple[str, ...] = ("molpy", "molexp")
"""Default Python packages whose source the introspection mount may read."""

PLUGIN_NAMESPACES: tuple[str, ...] = ("molpy", "molexp", "lammps")
"""Namespaces under which plugin tools are exposed at the gateway."""
