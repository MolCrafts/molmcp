"""Provider contract tests."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from molmcp import (
    CollectionIndex,
    Provider,
    Registry,
    create_server,
    discover_providers,
)
from molmcp import provider as provider_module
from molmcp.middleware import MissingAnnotationsError


def _server(*, providers, **kwargs):
    return create_server(
        "test",
        collection=CollectionIndex([], Registry()),
        providers=providers,
        discover_entry_points=False,
        **kwargs,
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


class ReservedProvider:
    name = "molcrafts"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def info() -> str:
            """Attempt to collide with a core tool."""
            return "bad"


class TestProviderRegistration:
    def test_explicit_provider_registers(self):
        server = _server(providers=[GoodProvider()])
        assert isinstance(server, FastMCP)

    async def test_explicit_provider_tool_callable(self):
        server = _server(providers=[GoodProvider()])
        result = await server.call_tool("good_good_tool", {"x": 21})
        text = result.content[0].text
        # Tool returns int 42, FastMCP serializes it
        assert "42" in text

    def test_unannotated_provider_rejected(self):
        with pytest.raises(MissingAnnotationsError) as ei:
            _server(providers=[UnannotatedProvider()])
        assert "bad_tool" in str(ei.value)

    def test_no_validate_skips_check(self):
        server = _server(
            providers=[UnannotatedProvider()],
            validate_annotations=False,
        )
        assert isinstance(server, FastMCP)

    def test_provider_protocol_runtime_check(self):
        assert isinstance(GoodProvider(), Provider)


class TestProviderDeduplication:
    def test_same_name_provider_fails_closed(self):
        p1 = GoodProvider()
        p2 = GoodProvider()
        with pytest.raises(ValueError, match="duplicate provider name: good"):
            _server(providers=[p1, p2])

    def test_core_namespace_is_reserved(self):
        with pytest.raises(ValueError, match="reserved provider name: molcrafts"):
            _server(providers=[ReservedProvider()])


def test_entry_point_name_is_provider_namespace_authority(monkeypatch):
    class EntryPoint:
        name = "declared"

        @staticmethod
        def load():
            return GoodProvider

    monkeypatch.setattr(
        provider_module.importlib.metadata,
        "entry_points",
        lambda **kwargs: [EntryPoint()],
    )
    failures: list[dict[str, str]] = []
    assert discover_providers(failures=failures) == []
    assert failures == [
        {
            "entry_point": "declared",
            "phase": "authority",
            "error_type": "NamespaceMismatch",
        }
    ]
