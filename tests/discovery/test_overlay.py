"""Domain capability overlay tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.evidence import EvidenceBuilder
from molmcp.discovery.overlay import OverlayContribution
from molmcp.discovery.overlay.catalog import CatalogOverlay, load_catalog
from molmcp.discovery.schema import Node, NodeKind

_CATALOG = """
[[capability]]
id = "compute.rdf"
title = "Radial distribution function"
summary = "Compute g(r) between atom selections."
implemented_by = ["compute.RDF"]
examples = ["examples/rdf.py"]
tags = ["analysis"]

[[capability]]
id = "missing.thing"
summary = "Declared but not implemented anywhere."
implemented_by = ["does.not.Exist"]
"""

_SOURCE = '''"""Compute module."""


class RDF:
    """Radial distribution function compute op."""

    def run(self):
        return 1
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def overlay_engine(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / "compute.py", _SOURCE)
    catalog = tmp_path / "capability_catalog.toml"
    catalog.write_text(_CATALOG, encoding="utf-8")
    overlay = CatalogOverlay(catalog, name="test")
    engine = DiscoveryEngine(
        DiscoveryConfig(cache_dir=tmp_path / "cache"), overlays=[overlay]
    )
    return engine, str(repo)


def test_load_catalog_parses_capabilities(tmp_path):
    catalog = tmp_path / "c.toml"
    catalog.write_text(_CATALOG, encoding="utf-8")
    caps = load_catalog(catalog)
    assert {c.id for c in caps} == {"compute.rdf", "missing.thing"}
    rdf = next(c for c in caps if c.id == "compute.rdf")
    assert rdf.implemented_by == ["compute.RDF"]
    assert rdf.tags == ["analysis"]


def test_overlay_adds_capability_nodes(overlay_engine):
    engine, repo = overlay_engine
    graph = engine.get_graph(repo)
    capabilities = {n.qualname for n in graph.nodes if n.kind == "capability"}
    assert capabilities == {"compute.rdf", "missing.thing"}


def test_overlay_links_provides_capability_edge(overlay_engine):
    engine, repo = overlay_engine
    graph = engine.get_graph(repo)
    rdf = next(n for n in graph.nodes if n.qualname == "compute.RDF")
    provides = {
        e.target
        for e in graph.edges
        if e.kind == "provides_capability"
    }
    assert rdf.id in provides


def test_unresolved_capability_target_is_kept(overlay_engine):
    engine, repo = overlay_engine
    graph = engine.get_graph(repo)
    names = {
        u.name
        for u in graph.unresolved
        if u.kind == "provides_capability"
    }
    assert "does.not.Exist" in names


def test_capability_is_discoverable(overlay_engine):
    engine, repo = overlay_engine
    query = engine.query(repo)
    hits = query.search("radial distribution", limit=10)
    assert "compute.rdf" in {n.qualname for n in hits}


def test_implementations_relation(overlay_engine):
    engine, repo = overlay_engine
    query = engine.query(repo)
    impls = {n.qualname for n in query.implementations("compute.rdf")}
    assert impls == {"compute.RDF"}


def test_find_capability_surfaces_overlay(overlay_engine):
    engine, repo = overlay_engine
    query = engine.query(repo)
    result = EvidenceBuilder(query).find_capability("radial distribution", 8)
    assert any(
        m["node"]["qualname"] == "compute.rdf" for m in result["matches"]
    )


def test_custom_overlay_protocol(tmp_path):
    """An overlay need not be a CatalogOverlay — just satisfy the protocol."""

    class StaticOverlay:
        name = "static"

        def applies_to(self, snapshot):
            return True

        def contribute(self, graph):
            node = Node(
                id="<x>#cap.demo#capability",
                kind=NodeKind.CAPABILITY,
                name="cap.demo",
                qualname="cap.demo",
                language="capability",
                file="<x>",
                start_line=0,
                end_line=0,
                summary="a demo capability",
            )
            return OverlayContribution(nodes=[node])

    repo = tmp_path / "repo"
    _write(repo / "m.py", "x = 1\n")
    engine = DiscoveryEngine(
        DiscoveryConfig(cache_dir=tmp_path / "cache"),
        overlays=[StaticOverlay()],
    )
    graph = engine.get_graph(str(repo))
    assert "cap.demo" in {n.qualname for n in graph.nodes}
