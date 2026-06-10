"""DiscoveryProvider MCP tool tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import call

from molmcp import create_server
from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.evidence import EvidenceBuilder
from molmcp.discovery.overlay.catalog import CatalogOverlay

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
        result = await call(server, "molmcp_search_symbols", {"query": "Widget"})
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
        result = await call(server, "molmcp_find_capability", {"task": "widget"})
        assert "matches" in result
        assert "snapshot" in result
        assert result["match_count"] == len(result["matches"])


_CAP_CATALOG = """
[[capability]]
id = "compute.rdf"
title = "Radial distribution function"
summary = "Compute g(r) between atom selections."
implemented_by = ["compute.RDF"]
tags = ["analysis"]
"""

_CAP_SOURCE = '''"""Compute module."""


class RDF:
    """Radial distribution function compute op."""

    def run(self):
        return 1
'''


@pytest.fixture
def capability_query(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "compute.py").write_text(_CAP_SOURCE, encoding="utf-8")
    catalog = tmp_path / "capability_catalog.toml"
    catalog.write_text(_CAP_CATALOG, encoding="utf-8")
    engine = DiscoveryEngine(
        DiscoveryConfig(cache_dir=tmp_path / "cache"),
        overlays=[CatalogOverlay(catalog, name="test")],
    )
    return engine.query(str(repo))


class TestCapabilityFirst:
    def test_capability_match_ranks_first(self, capability_query):
        result = EvidenceBuilder(capability_query).find_capability(
            "radial distribution", 8
        )
        top = result["matches"][0]
        assert top["match_type"] == "capability"
        assert top["node"]["qualname"] == "compute.rdf"
        implemented = {n["qualname"] for n in top["implemented_by"]}
        assert implemented == {"compute.RDF"}

    def test_implemented_symbols_deduped_from_symbol_stage(self, capability_query):
        result = EvidenceBuilder(capability_query).find_capability(
            "radial distribution", 8
        )
        symbol_quals = {
            m["node"]["qualname"]
            for m in result["matches"]
            if m["match_type"] == "symbol"
        }
        assert "compute.RDF" not in symbol_quals

    def test_ranks_are_consecutive_across_stages(self, capability_query):
        result = EvidenceBuilder(capability_query).find_capability("compute", 8)
        ranks = [m["rank"] for m in result["matches"]]
        assert ranks == list(range(1, len(ranks) + 1))

    async def test_no_capability_source_yields_symbol_matches_only(self, server):
        result = await call(server, "molmcp_find_capability", {"task": "widget"})
        assert result["matches"]
        assert all(m["match_type"] == "symbol" for m in result["matches"])


_PROV_SOURCE = '''"""m module."""


def helper():
    """A helper others call."""
    return 1


def driver():
    """Calls helper."""
    return helper()
'''

_PROVENANCE_VALUES = {"ast", "heuristic", "resolved"}


@pytest.fixture
def prov_repo(tmp_path):
    repo = tmp_path / "prov_repo"
    repo.mkdir()
    (repo / "m.py").write_text(_PROV_SOURCE, encoding="utf-8")
    return repo


class TestProvenanceExposure:
    async def test_relations_items_carry_provenance(self, tmp_path, prov_repo):
        server = create_server(
            "prov",
            discovery_sources=[str(prov_repo)],
            discovery_config=DiscoveryConfig(cache_dir=tmp_path / "pc"),
            discover_entry_points=False,
        )
        result = await call(
            server,
            "molmcp_relations",
            {"qualname": "m.helper", "relation": "callers"},
        )
        assert result["result_count"] >= 1
        for item in result["results"]:
            assert item["provenance"] in _PROVENANCE_VALUES

    def test_find_capability_callers_carry_provenance(self, tmp_path, prov_repo):
        from molmcp.discovery import DiscoveryEngine

        engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "pc2"))
        query = engine.query(str(prov_repo))
        result = EvidenceBuilder(query).find_capability("helper", 8)
        match = next(
            m for m in result["matches"] if m["node"]["qualname"] == "m.helper"
        )
        assert match["callers"]
        for caller in match["callers"]:
            assert caller["provenance"] in _PROVENANCE_VALUES


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
