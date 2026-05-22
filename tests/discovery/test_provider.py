"""DiscoveryProvider MCP tool tests."""

from __future__ import annotations

from pathlib import Path

import pytest  # noqa: F401
from conftest import call

from molmcp import create_server
from molmcp.discovery import DiscoveryConfig

_DISCOVERY_TOOLS = {
    "molmcp_find_capability",
    "molmcp_search_symbols",
    "molmcp_describe_symbol",
    "molmcp_relations",
    "molmcp_outline",
    "molmcp_refresh",
}
_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestToolSurface:
    async def test_discovery_tools_registered(self, server):
        names = {t.name for t in await server.list_tools()}
        assert _DISCOVERY_TOOLS <= names

    async def test_all_tools_are_read_only(self, server):
        for tool in await server.list_tools():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.readOnlyHint is True, tool.name


class TestOutline:
    async def test_outline_lists_fixture_package(self, server):
        result = await call(server, "molmcp_outline")
        quals = {m["qualname"] for m in result["modules"]}
        assert "fixture_pkg" in quals

    async def test_response_carries_snapshot_block(self, server):
        result = await call(server, "molmcp_outline")
        snapshot = result["snapshot"]
        assert snapshot["origin"] == "local"
        assert snapshot["freshness"] == "fresh"
        assert snapshot["snapshot_id"].startswith("local:hash:")


class TestSearch:
    async def test_finds_class(self, server):
        result = await call(
            server, "molmcp_search_symbols", {"query": "Widget"}
        )
        assert "fixture_pkg.Widget" in {r["qualname"] for r in result["results"]}

    async def test_kind_filter(self, server):
        result = await call(
            server,
            "molmcp_search_symbols",
            {"query": "Widget", "kind": "class"},
        )
        assert result["results"]
        assert all(r["kind"] == "class" for r in result["results"])


class TestDescribeSymbol:
    async def test_describe_class(self, server):
        result = await call(
            server, "molmcp_describe_symbol", {"qualname": "fixture_pkg.Widget"}
        )
        symbol = result["symbol"]
        assert symbol["kind"] == "class"
        assert "source" not in symbol

    async def test_include_source(self, server):
        result = await call(
            server,
            "molmcp_describe_symbol",
            {"qualname": "fixture_pkg.Widget", "include_source": True},
        )
        assert "class Widget" in result["symbol"]["source"]

    async def test_unknown_symbol(self, server):
        result = await call(
            server,
            "molmcp_describe_symbol",
            {"qualname": "fixture_pkg.NoSuchThing"},
        )
        assert "error" in result


class TestRelations:
    async def test_relation_shape(self, server):
        result = await call(
            server,
            "molmcp_relations",
            {"qualname": "fixture_pkg.Widget", "relation": "references"},
        )
        assert result["relation"] == "references"
        assert "results" in result

    async def test_unknown_relation(self, server):
        result = await call(
            server,
            "molmcp_relations",
            {"qualname": "fixture_pkg.Widget", "relation": "bogus"},
        )
        assert "error" in result
        assert "valid_relations" in result


class TestFindCapability:
    async def test_returns_matches_and_snapshot(self, server):
        result = await call(
            server, "molmcp_find_capability", {"task": "widget"}
        )
        assert "matches" in result
        assert "snapshot" in result
        assert result["match_count"] == len(result["matches"])


class TestRefresh:
    async def test_refresh_reindexes(self, server):
        result = await call(server, "molmcp_refresh")
        assert result["refreshed"] is True
        assert result["indexed"]["nodes"] > 0


class TestSourceErrors:
    async def test_unknown_source(self, server):
        result = await call(
            server, "molmcp_outline", {"source": "pkg:definitely_not_real"}
        )
        assert "error" in result
        assert "available_sources" in result


class TestServerConstruction:
    async def test_create_server_passes_annotation_validation(self, tmp_path):
        server = create_server(
            "annotations-check",
            discovery_sources=["pkg:fixture_pkg"],
            discovery_config=DiscoveryConfig(cache_dir=tmp_path / "c"),
            discover_entry_points=False,
            validate_annotations=True,
        )
        assert server is not None

    async def test_outline_on_local_path_source(self, tmp_path):
        server = create_server(
            "path-source",
            discovery_sources=[str(_REPO_ROOT / "src" / "molmcp" / "discovery")],
            discovery_config=DiscoveryConfig(cache_dir=tmp_path / "c"),
            discover_entry_points=False,
        )
        result = await call(server, "molmcp_outline")
        assert result["modules"]
        assert result["snapshot"]["origin"] == "local"

    async def test_no_sources_registers_no_discovery_tools(self, tmp_path):
        server = create_server(
            "empty",
            discovery_sources=None,
            discover_entry_points=False,
        )
        names = {t.name for t in await server.list_tools()}
        assert not (_DISCOVERY_TOOLS & names)
