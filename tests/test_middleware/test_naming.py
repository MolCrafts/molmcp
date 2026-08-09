"""Bare tool naming contract — forbid plane_ / plane_plane_ prefixes."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from molmcp.middleware.naming import (
    ToolNamingError,
    assert_plane_tool_names,
    validate_plane_tool_names,
)
from molmcp.server import create_plane


class _PrefixedProvider:
    """Illegal: tool name repeats the plane id."""

    name = "molexp"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        def molexp_list_projects() -> list:
            """Would become molexp_molexp / molexp__molexp_list_projects."""
            return []


class _BareProvider:
    name = "molexp"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        def list_projects() -> list:
            """Correct bare name."""
            return []


def test_prefixed_tool_rejected_at_create_plane():
    with pytest.raises(ToolNamingError, match="prefixed with plane id"):
        create_plane(
            "molexp",
            provider=_PrefixedProvider(),
            discover_entry_points=False,
        )


def test_bare_tool_accepted():
    server = create_plane(
        "molexp",
        provider=_BareProvider(),
        discover_entry_points=False,
    )
    assert server.name == "molexp"


def test_validate_detects_double_substring():
    mcp = FastMCP("molexp")

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    def molexp_molexp_oops() -> str:
        return "x"

    msgs = validate_plane_tool_names(mcp, "molexp")
    assert any("doubled" in m or "prefixed" in m for m in msgs)
    with pytest.raises(ToolNamingError):
        assert_plane_tool_names(mcp, "molexp")


def test_builtin_planes_pass_naming():
    create_plane("catalog")
    # molcrafts with empty collection
    from molmcp import CollectionIndex

    create_plane(
        "molcrafts",
        collection=CollectionIndex([]),
        discover_entry_points=False,
    )
