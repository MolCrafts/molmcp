"""Contract tests for the clean four-tool MCP surface."""

from __future__ import annotations

import json
from urllib.parse import quote

from conftest import call

_CORE_TOOLS = {
    "molcrafts_info",
    "molcrafts_search",
    "molcrafts_describe",
    "molcrafts_explore",
}


async def test_exact_four_core_tools(server):
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == _CORE_TOOLS
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True


async def test_search_returns_stable_non_executable_symbol_refs(server):
    result = await call(server, "molcrafts_search", {"query": "Widget"})
    assert result["result_count"] >= 1
    hit = next(
        item for item in result["results"] if item["title"] == "fixture_pkg.Widget"
    )
    assert hit["ref"].startswith("fixture@local:hash:")
    assert hit["ref"].endswith("fixture_pkg/__init__.py#fixture_pkg.Widget#class")
    assert hit["executable"] is False
    assert hit["freshness"] == "fresh"


async def test_describe_requires_exact_returned_ref(server):
    search = await call(server, "molcrafts_search", {"query": "Widget"})
    ref = next(
        item["ref"]
        for item in search["results"]
        if item["title"] == "fixture_pkg.Widget"
    )
    detail = await call(
        server,
        "molcrafts_describe",
        {"ref": ref, "include_source": True},
    )
    assert detail["detail"]["qualname"] == "fixture_pkg.Widget"
    assert "class Widget" in detail["detail"]["source_code"]

    stale = await call(server, "molcrafts_describe", {"ref": ref + "-stale"})
    assert stale["error"] == "ref_not_found_or_stale"


async def test_explore_is_bounded_and_reports_coverage(server):
    result = await call(
        server,
        "molcrafts_explore",
        {"task": "Widget", "budget_chars": 4000},
    )
    assert result["budget_chars"] == 4000
    assert result["used_chars"] <= 4000
    assert result["coverage"]["successful_sources"] == 1
    assert result["freshness"]["overall"] == "fresh"
    assert all(hit["executable"] is False for hit in result["hits"])


async def test_info_and_resources(server):
    info = await call(server, "molcrafts_info")
    assert info["coverage"]["source_count"] == 1
    assert info["registry"]["item_count"] == 0

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
        if item["title"] == "fixture_pkg.Widget"
    )
    uri = f"molcrafts://source/fixture/symbol/{quote(ref, safe='')}"
    resource = await server.read_resource(uri)
    payload = json.loads(resource.contents[0].content)
    assert payload["ref"] == ref
    assert payload["source"] == "fixture"
    assert payload["provenance"]["type"] == "code_graph"


async def test_every_core_response_has_freshness_and_provenance(server):
    search = await call(server, "molcrafts_search", {"query": "Widget"})
    assert search["freshness"]["overall"] == "fresh"
    assert search["provenance"]["type"] == "federated_search"

    missing = await call(server, "molcrafts_describe", {"ref": "invalid"})
    assert missing["freshness"] == "unknown"
    assert missing["provenance"]["type"] == "exact_ref_lookup"
