"""Routing guide unit tests — no MCP server required."""

from __future__ import annotations

from molmcp.guide import build_routing_guide, intent_tags_for_task, role_for_source


def test_intent_detects_packing_and_structure() -> None:
    tags = intent_tags_for_task(
        "build a coarse-grained monomer and pack 10 copies into a box"
    )
    assert "packing" in tags
    assert "structure" in tags


def test_role_for_source_from_inventory_names() -> None:
    assert role_for_source("molcrafts-molpack") == "packing"
    assert role_for_source("molpy") == "structure"
    assert role_for_source("molq") == "scheduling"


def test_guide_checklist_prefers_installed_packing_source() -> None:
    guide = build_routing_guide(
        "pack water into a cubic box",
        sources={
            "molcrafts-molpack": {
                "status": "ok",
                "spec": "pkg:molpack",
                "freshness": "fresh",
            },
            "molpy": {"status": "ok", "spec": "pkg:molpy", "freshness": "fresh"},
            "mkdocs": {"status": "ok", "spec": "pkg:mkdocs", "freshness": "fresh"},
        },
    )
    assert guide["ok"] is True
    packing = next(c for c in guide["checklist"] if c["role"] == "packing")
    assert packing["available"] is True
    assert any("molpack" in p for p in packing["prefer_packages"])
    assert any("molpack" in q for q in guide["suggested_queries"])
    assert "rules" in guide and len(guide["rules"]) >= 3


def test_guide_warns_when_intent_package_missing() -> None:
    guide = build_routing_guide(
        "pack molecules into a box",
        sources={"molpy": {"status": "ok", "spec": "pkg:molpy"}},
    )
    packing = next(c for c in guide["checklist"] if c["role"] == "packing")
    assert packing["available"] is False
    assert guide["warnings"]
