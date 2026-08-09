"""Provider contract tests — one plane per process."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from molmcp import (
    Provider,
    create_plane,
    discover_providers,
)
from molmcp import provider as provider_module
from molmcp.middleware import MissingAnnotationsError


def _server(*, provider, **kwargs):
    return create_plane(
        provider.name,
        provider=provider,
        discover_entry_points=False,
        **kwargs,
    )


class GoodProvider:
    name = "good"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        def double(x: int) -> int:
            """Return x doubled."""
            return x * 2


class UnannotatedProvider:
    name = "bad"

    def register(self, mcp: FastMCP) -> None:
        @mcp.tool
        def bare() -> str:
            """A tool with no annotations."""
            return "boo"


class TestProviderRegistration:
    def test_explicit_provider_registers(self):
        server = _server(provider=GoodProvider())
        assert isinstance(server, FastMCP)
        assert server.name == "good"

    async def test_explicit_provider_tool_callable(self):
        server = _server(provider=GoodProvider())
        # Bare tool name — plane id is the server name, not a tool prefix.
        result = await server.call_tool("double", {"x": 21})
        text = result.content[0].text
        assert "42" in text

    def test_unannotated_provider_rejected(self):
        with pytest.raises(MissingAnnotationsError) as ei:
            _server(provider=UnannotatedProvider())
        assert "bare" in str(ei.value)

    def test_no_validate_skips_check(self):
        server = _server(
            provider=UnannotatedProvider(),
            validate_annotations=False,
        )
        assert isinstance(server, FastMCP)

    def test_provider_protocol_runtime_check(self):
        assert isinstance(GoodProvider(), Provider)

    def test_plane_provider_name_must_match(self):
        with pytest.raises(ValueError, match="does not match plane"):
            create_plane(
                "other",
                provider=GoodProvider(),
                discover_entry_points=False,
            )


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


def test_only_available_silently_omits_failed_probe(monkeypatch):
    """Runtime catalog omit — not a pytest.skip."""

    class MissingDepProvider:
        name = "ghost"

        @staticmethod
        def probe() -> bool:
            return False

        def register(self, mcp) -> None:  # pragma: no cover
            raise RuntimeError("should not register")

    class EntryPoint:
        name = "ghost"

        @staticmethod
        def load():
            return MissingDepProvider

    monkeypatch.setattr(
        provider_module.importlib.metadata,
        "entry_points",
        lambda **kwargs: [EntryPoint()],
    )
    assert discover_providers(only_available=False)[0].name == "ghost"
    assert discover_providers(only_available=True) == []
