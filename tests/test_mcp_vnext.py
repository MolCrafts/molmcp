"""Contract tests for the hierarchical molcrafts plane surface."""

from __future__ import annotations

from urllib.parse import quote

from conftest import call

from molmcp import create_plane
from molmcp.planes import route_task

_CORE_TOOLS = {
    "info",
    "packages",
    "outline",
    "open",
    "compose",
    "search",
    "suggest",
}


async def test_core_tools_present(server):
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert _CORE_TOOLS <= names
    # No legacy aliases / mega-server prefixes.
    assert not any(n.startswith("molcrafts_") for n in names)
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


async def test_packages_injects_markdown(server):
    result = await call(server, "packages")
    assert result["ok"] is True
    assert "markdown" in result and result["markdown"]
    assert result["data"]["packages"]


async def test_outline_and_open_path(server):
    outline = await call(server, "outline", {"source": "fixture"})
    assert outline["ok"] is True
    assert outline["markdown"]

    search = await call(server, "search", {"query": "Widget", "sources": ["fixture"]})
    assert search["result_count"] >= 1
    ref = next(
        item["ref"]
        for item in search["results"]
        if item.get("title") == "fixture_pkg.Widget"
        or "Widget" in (item.get("title") or "")
    )
    opened = await call(server, "open", {"ref": ref})
    assert opened["ok"] is True
    assert opened["markdown"]
    assert opened["data"]["coverage"]["examples"] >= 0

    stale = await call(server, "open", {"ref": ref + "-stale"})
    assert stale["ok"] is False
    assert stale["code"] == "SYMBOL_NOT_FOUND"


async def test_compose(server):
    pack = await call(
        server,
        "compose",
        {"task": "Widget", "budget_chars": 4000},
    )
    assert pack["ok"] is True
    assert pack["markdown"]


async def test_info_and_resources(server):
    info = await call(server, "info")
    assert info["coverage"]["source_count"] == 1

    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    assert {str(resource.uri) for resource in resources} == {
        "molcrafts://workspace/context"
    }

    def _template_uri(t) -> str:
        return str(
            getattr(t, "uri_template", None) or getattr(t, "uriTemplate", "") or ""
        )

    assert any("capability" in _template_uri(t) for t in templates)
    assert any("symbol" in _template_uri(t) for t in templates)
    _ = quote


async def test_catalog_plane_lists_and_routes():
    catalog = create_plane("catalog")
    tools = await catalog.list_tools()
    names = {t.name for t in tools}
    assert names == {"list_planes", "route"}

    planes = await call(catalog, "list_planes")
    assert planes["ok"] is True
    ids = {p["id"] for p in planes["planes"]}
    assert "catalog" in ids and "molcrafts" in ids

    routed = await call(catalog, "route", {"task": "draw dopamine in the viewer"})
    assert any(m["plane"] == "molvis" for m in routed["planes"])
    # Pure function path matches tool
    assert route_task("submit a slurm job")["planes"][0]["plane"] == "molq"


async def test_multi_provider_server_rejected():
    from fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    class P1:
        name = "a"

        def register(self, mcp: FastMCP) -> None:
            @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
            def t() -> str:
                return "a"

    class P2:
        name = "b"

        def register(self, mcp: FastMCP) -> None:
            @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
            def t() -> str:
                return "b"

    import pytest

    with pytest.raises(ValueError, match="multi-provider"):
        create_plane("a", providers=[P1(), P2()], discover_entry_points=False)
