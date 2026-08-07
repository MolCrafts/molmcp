"""Plane tool naming contract — no double prefixes, no plane-id tool prefix.

Each MCP process is already named after its plane (``molexp``, ``molvis``, …).
Tools register with **bare** names (``list_projects``, ``open``). Clients then
see ``molexp__list_projects``.

Forbidden (legacy mega-server mount + tool prefix):

* tool ``molexp_list_projects`` on server ``molexp`` → client
  ``molexp__molexp_list_projects`` or mount-era ``molexp_molexp_list_projects``
* tool name containing ``{plane}_{plane}_``
* tool name starting with ``{plane}_`` when *plane* is the process plane id
"""

from __future__ import annotations

import re

from fastmcp import FastMCP

from .annotations_validator import _iter_tools

# Bare tool names: lowercase start, then letters/digits/underscore only.
_BARE_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolNamingError(RuntimeError):
    """Raised when a plane registers a tool that violates the bare-name contract."""


def validate_plane_tool_names(mcp: FastMCP, plane_id: str) -> list[str]:
    """Return violation messages; empty means all tool names are clean.

    Rules for every registered tool name *n*:

    1. Matches ``^[a-z][a-z0-9_]*$`` (bare identifier).
    2. Does **not** start with ``{plane_id}_`` (plane is the server name).
    3. Does **not** contain ``{plane_id}_{plane_id}`` (classic double mount).
    """
    plane = plane_id.strip().lower()
    if not plane:
        return ["plane id is empty"]

    prefix = f"{plane}_"
    double = f"{plane}_{plane}"
    warnings: list[str] = []

    for tool in _iter_tools(mcp):
        name = tool.name
        if not _BARE_TOOL_RE.fullmatch(name):
            warnings.append(
                f"tool {name!r} is not a bare name "
                f"(expected ^[a-z][a-z0-9_]*$, plane={plane!r})"
            )
            continue
        if name.startswith(prefix):
            bare = name.removeprefix(prefix)
            warnings.append(
                f"tool {name!r} is prefixed with plane id {plane!r}; "
                f"register bare names only (client will show {plane}__{bare})"
            )
        if double in name or name.startswith(double):
            warnings.append(
                f"tool {name!r} contains doubled plane prefix {double!r} "
                f"(forbidden; was mount-era molexp_molexp_* style)"
            )
    return warnings


def assert_plane_tool_names(mcp: FastMCP, plane_id: str) -> None:
    """Raise :class:`ToolNamingError` if any tool violates the naming contract."""
    bad = validate_plane_tool_names(mcp, plane_id)
    if bad:
        raise ToolNamingError(
            f"Plane {plane_id!r} tool naming contract failed:\n  - "
            + "\n  - ".join(bad)
        )


__all__ = [
    "ToolNamingError",
    "assert_plane_tool_names",
    "validate_plane_tool_names",
]
