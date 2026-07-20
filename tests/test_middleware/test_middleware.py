"""Middleware tests — path safety, response limit, annotations validator."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from molmcp import CollectionIndex, Registry, create_server
from molmcp.middleware import MissingAnnotationsError, validate_tool_annotations


def _server(*, providers, **kwargs):
    return create_server(
        "t",
        collection=CollectionIndex([], Registry()),
        providers=providers,
        discover_entry_points=False,
        **kwargs,
    )


class _BigStringProvider:
    name = "big"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def emit_big(size: int) -> str:
            """Emit a string of ``size`` 'A' characters."""
            return "A" * size


class _PathToolProvider:
    name = "pth"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def open_file(file_path: str) -> str:
            """Pretend to open ``file_path``."""
            return f"opened {file_path}"


class TestResponseLimitMiddleware:
    async def test_truncates_large_response(self):
        server = _server(
            providers=[_BigStringProvider()],
            response_limit_bytes=1024,
        )
        result = await server.call_tool("big_emit_big", {"size": 5000})
        text = result.content[0].text
        assert "truncated" in text
        assert len(text.encode()) < 5000

    async def test_passes_small_response(self):
        server = _server(
            providers=[_BigStringProvider()],
            response_limit_bytes=1024,
        )
        result = await server.call_tool("big_emit_big", {"size": 100})
        text = result.content[0].text
        assert "truncated" not in text


class TestPathSafetyMiddleware:
    async def test_rejects_traversal(self):
        from fastmcp.exceptions import ToolError

        server = _server(providers=[_PathToolProvider()])
        with pytest.raises(ToolError, match="traversal"):
            await server.call_tool("pth_open_file", {"file_path": "../../etc/passwd"})

    async def test_passes_safe_path(self):
        server = _server(providers=[_PathToolProvider()])
        result = await server.call_tool("pth_open_file", {"file_path": "data/foo.txt"})
        text = result.content[0].text
        assert "opened data/foo.txt" in text


class TestAnnotationsValidator:
    def test_warns_on_missing(self):
        # Build a server with validation off, then validate by hand to confirm
        # the warning surfaces.
        class _Bad:
            name = "bad"

            def register(self, mcp):
                @mcp.tool
                def t():
                    """No annotations."""
                    return 1

        server = _server(
            providers=[_Bad()],
            validate_annotations=False,
        )
        warnings = validate_tool_annotations(server, strict=False)
        assert warnings  # at least one warning produced

    def test_strict_raises_on_missing(self):
        class _Bad:
            name = "bad"

            def register(self, mcp):
                @mcp.tool
                def t():
                    """No annotations."""
                    return 1

        server = _server(
            providers=[_Bad()],
            validate_annotations=False,
        )
        with pytest.raises(MissingAnnotationsError):
            validate_tool_annotations(server, strict=True)
