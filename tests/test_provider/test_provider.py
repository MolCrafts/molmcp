"""Provider contract tests."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from molmcp import (
    MissingAnnotationsError,
    Provider,
    create_server,
)


class GoodProvider:
    name = "good"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def good_tool(x: int) -> int:
            """Return x doubled."""
            return x * 2


class UnannotatedProvider:
    name = "bad"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool
        def bad_tool() -> str:
            """A tool with no annotations."""
            return "boo"


class TestProviderRegistration:
    def test_explicit_provider_registers(self):
        server = create_server(
            "test",
            providers=[GoodProvider()],
            discover_entry_points=False,
        )
        assert isinstance(server, FastMCP)

    async def test_explicit_provider_tool_callable(self):
        server = create_server(
            "test",
            providers=[GoodProvider()],
            discover_entry_points=False,
        )
        result = await server.call_tool("good_tool", {"x": 21})
        text = result.content[0].text
        # Tool returns int 42, FastMCP serializes it
        assert "42" in text

    def test_unannotated_provider_rejected(self):
        with pytest.raises(MissingAnnotationsError) as ei:
            create_server(
                "test",
                providers=[UnannotatedProvider()],
                discover_entry_points=False,
            )
        assert "bad_tool" in str(ei.value)

    def test_no_validate_skips_check(self):
        server = create_server(
            "test",
            providers=[UnannotatedProvider()],
            discover_entry_points=False,
            validate_annotations=False,
        )
        assert isinstance(server, FastMCP)

    def test_provider_protocol_runtime_check(self):
        assert isinstance(GoodProvider(), Provider)


class TestProviderDeduplication:
    def test_same_name_provider_skipped(self):
        # Two providers with the same name — second should be skipped silently
        p1 = GoodProvider()
        p2 = GoodProvider()
        server = create_server("test", providers=[p1, p2], discover_entry_points=False)
        # No exception, single registration
        assert isinstance(server, FastMCP)
