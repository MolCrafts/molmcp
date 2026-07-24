"""Contract tests for the hierarchical molcrafts MCP surface."""

from __future__ import annotations

import json
from urllib.parse import quote

from conftest import call

_CORE_TOOLS = {
    "molcrafts_info",
    "molcrafts_packages",
    "molcrafts_outline",
    "molcrafts_open",
    "molcrafts_compose",
    "molcrafts_search",
    "molcrafts_suggest",
    # aliases
    "molcrafts_guide",
    "molcrafts_describe",
    "molcrafts_usage",
    "molcrafts_explore",
}


async def test_core_tools_present(server):
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert _CORE_TOOLS <= names
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


async def test_packages_injects_markdown(server):
    result = await call(server, "molcrafts_packages")
    assert result["ok"] is True
    assert "markdown" in result and result["markdown"]
    assert result["data"]["packages"]


async def test_outline_and_open_path(server):
    outline = await call(server, "molcrafts_outline", {"source": "fixture"})
    assert outline["ok"] is True
    assert outline["markdown"]

    search = await call(
        server, "molcrafts_search", {"query": "Widget", "sources": ["fixture"]}
    )
    assert search["result_count"] >= 1
    ref = next(
        item["ref"]
        for item in search["results"]
        if item.get("title") == "fixture_pkg.Widget"
        or "Widget" in (item.get("title") or "")
    )
    opened = await call(server, "molcrafts_open", {"ref": ref})
    assert opened["ok"] is True
    assert opened["markdown"]
    assert opened["data"]["coverage"]["examples"] >= 0

    stale = await call(server, "molcrafts_open", {"ref": ref + "-stale"})
    assert stale["ok"] is False
    assert stale["code"] == "SYMBOL_NOT_FOUND"


async def test_describe_usage_aliases_open(server):
    search = await call(server, "molcrafts_search", {"query": "Widget"})
    ref = search["results"][0]["ref"]
    desc = await call(server, "molcrafts_describe", {"ref": ref})
    assert desc["ok"] is True
    usage = await call(server, "molcrafts_usage", {"ref": ref})
    assert usage["ok"] is True
    assert "usage" in usage or "data" in usage


async def test_compose_and_explore_alias(server):
    pack = await call(
        server,
        "molcrafts_compose",
        {"task": "Widget", "budget_chars": 4000},
    )
    assert pack["ok"] is True
    assert pack["markdown"]
    explore = await call(
        server,
        "molcrafts_explore",
        {"task": "Widget", "budget_chars": 4000},
    )
    assert explore["ok"] is True


async def test_info_and_resources(server):
    info = await call(server, "molcrafts_info")
    assert info["coverage"]["source_count"] == 1

    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    assert {str(resource.uri) for resource in resources} == {
        "molcrafts://workspace/context"
    }
    assert {template.uri_template for template in templates} == {
        "molcrafts://capability/{namespace}/{name}",
        "molcrafts://source/{source}/symbol/{symbol}",
    }


async def test_source_symbol_resource_requires_exact_snapshot_ref(server):
    search = await call(server, "molcrafts_search", {"query": "Widget"})
    ref = next(
        item["ref"]
        for item in search["results"]
        if "Widget" in (item.get("title") or "")
    )
    uri = f"molcrafts://source/fixture/symbol/{quote(ref, safe='')}"
    resource = await server.read_resource(uri)
    payload = json.loads(resource.contents[0].content)
    assert payload["ref"] == ref
    assert payload["source"] == "fixture"
    assert payload["provenance"]["type"] == "code_graph"
