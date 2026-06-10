"""Proof that the engine is fully domain-agnostic without any overlay."""

from __future__ import annotations

from pathlib import Path

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.overlay import load_overlays

_SOURCE = '''"""A module."""


def add(a, b):
    """Add two numbers."""
    return a + b


class Calc:
    """A calculator."""
'''


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(_SOURCE, encoding="utf-8")
    return repo


def test_engine_works_without_overlays(tmp_path):
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"), overlays=[])
    graph = engine.get_graph(str(_repo(tmp_path)))
    assert {n.qualname for n in graph.nodes} >= {"calc.add", "calc.Calc"}
    assert not any(n.kind == "capability" for n in graph.nodes)


def test_all_queries_work_without_overlays(tmp_path):
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"), overlays=[])
    query = engine.query(str(_repo(tmp_path)))
    assert query.search("calculator")
    assert query.get_node("calc.Calc") is not None
    assert query.outline()["modules"]
    # capability-specific walks simply return nothing, never error
    assert query.implementations("calc.Calc") == []


def test_load_overlays_returns_list(tmp_path):
    # molmcp itself registers no overlays; discovery must still be a list.
    assert isinstance(load_overlays(), list)
