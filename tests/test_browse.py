"""Hierarchical browse facade — packages / outline / open / compose."""

from __future__ import annotations

from molmcp import CollectionIndex, SourceBinding
from molmcp.collection.browse import (
    compose_context,
    open_ref,
    outline_source,
    packages_catalog,
    search_scoped,
)
from molmcp.discovery import DiscoveryConfig
from molmcp.discovery.engine import DiscoveryEngine


def _fixture_collection(tmp_path):
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    return CollectionIndex(
        [
            SourceBinding(
                name="fixture",
                spec="pkg:fixture_pkg",
                engine=engine,
                namespace="fixture",
            )
        ],
        None,
    )


def test_packages_catalog_has_markdown_and_cards(tmp_path):
    col = _fixture_collection(tmp_path)
    page = packages_catalog(col)
    assert page["ok"] is True
    assert page["markdown"]
    assert "# MolCrafts packages" in page["markdown"]
    cards = page["data"]["packages"]
    assert any(c["name"] == "fixture" for c in cards)
    fixture = next(c for c in cards if c["name"] == "fixture")
    assert fixture["status"] == "ok"
    assert fixture["module_count"] is not None


def test_outline_requires_source(tmp_path):
    col = _fixture_collection(tmp_path)
    miss = outline_source(col, "")
    assert miss["ok"] is False
    assert miss["code"] == "SOURCE_REQUIRED"
    unknown = outline_source(col, "no-such-source")
    assert unknown["ok"] is False
    assert unknown["code"] == "SOURCE_NOT_FOUND"


def test_outline_lists_modules_with_markdown(tmp_path):
    col = _fixture_collection(tmp_path)
    page = outline_source(col, "fixture")
    assert page["ok"] is True
    assert page["markdown"]
    assert page["data"]["module_count"] >= 1
    quals = {m["qualname"] for m in page["data"]["modules"]}
    assert any("fixture_pkg" in (q or "") for q in quals)
    # path filter is hierarchical (narrow or empty — never widens)
    narrowed = outline_source(col, "fixture", path="fixture_pkg")
    assert narrowed["ok"] is True
    assert narrowed["data"]["module_count"] <= page["data"]["module_count"]


def test_open_miss_and_hit(tmp_path):
    col = _fixture_collection(tmp_path)
    miss = open_ref(col, "no-such-ref")
    assert miss["ok"] is False
    assert miss["code"] == "SYMBOL_NOT_FOUND"

    hits = search_scoped(col, "Widget")
    assert hits["ok"] is True
    assert hits["result_count"] >= 1
    ref = hits["results"][0]["ref"]
    page = open_ref(col, ref)
    assert page["ok"] is True
    assert page["markdown"]
    assert "coverage" in page["data"]
    assert page["data"]["coverage"]["examples"] >= 0


def test_compose_returns_injectable_markdown(tmp_path):
    col = _fixture_collection(tmp_path)
    pack = compose_context(col, task="Widget greet", budget_chars=8000)
    assert pack["ok"] is True
    assert pack["markdown"]
    assert "MolCrafts packages" in pack["markdown"] or "Suggest" in pack["markdown"]


def test_search_scoped_to_source(tmp_path):
    col = _fixture_collection(tmp_path)
    hits = search_scoped(col, "Widget", sources=["fixture"])
    assert hits["ok"] is True
    assert hits["result_count"] >= 1
    assert all(r.get("source") == "fixture" for r in hits["results"])
    empty = search_scoped(col, "Widget", sources=["not-a-source"])
    assert empty["ok"] is False
    assert empty["code"] == "SOURCE_NOT_FOUND"
    assert empty["result_count"] == 0
