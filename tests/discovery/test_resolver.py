"""Resolver (phase 2) tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmcp.discovery.config import DiscoveryConfig
from molmcp.discovery.extract import Extractor
from molmcp.discovery.resolve import Resolver
from molmcp.discovery.schema import CodeGraph, EdgeKind
from molmcp.discovery.source.local import resolve_local_path

_CALC = '''"""Calculator package."""


def add(a, b):
    """Add two numbers.

    Example:
        ```python
        add(2, 3)
        ```
    """
    return a + b


def mul(a, b):
    """Multiply by repeated addition."""
    total = 0
    for _ in range(b):
        total = add(total, a)
    return total


class Base:
    """A base class."""


class Calc(Base):
    """A calculator built on Base."""

    def run(self):
        return add(mul(2, 3), 1)
'''

_TEST_CALC = '''"""Tests for calc."""

from calc import add


def test_add():
    assert add(1, 1) == 2
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def graph(tmp_path) -> CodeGraph:
    repo = tmp_path / "repo"
    _write(repo / "calc.py", _CALC)
    _write(repo / "test_calc.py", _TEST_CALC)
    snapshot = resolve_local_path(
        repo, str(repo), DiscoveryConfig(cache_dir=tmp_path / "_c")
    )
    return Resolver().resolve(Extractor().extract(snapshot))


def _edges(graph: CodeGraph, kind: str) -> list:
    return [e for e in graph.edges if e.kind == kind]


def _node(graph: CodeGraph, qualname: str):
    for n in graph.nodes:
        if n.qualname == qualname:
            return n
    return None


def test_calls_resolve_to_node_ids(graph):
    add = _node(graph, "calc.add")
    mul = _node(graph, "calc.mul")
    call_edges = _edges(graph, EdgeKind.CALLS)
    linked = {(e.source, e.target) for e in call_edges}
    assert (mul.id, add.id) in linked
    for edge in call_edges:
        assert edge.provenance != "ast"


def test_extends_edge_links_subclass(graph):
    base = _node(graph, "calc.Base")
    calc = _node(graph, "calc.Calc")
    extends = {(e.source, e.target) for e in _edges(graph, EdgeKind.EXTENDS)}
    assert (calc.id, base.id) in extends


def test_dynamic_reference_stays_unresolved(graph):
    # `range(b)` has no node in the snapshot — it must not be invented.
    names = {r.name for r in graph.unresolved}
    assert "range" in names


def test_test_function_classified_and_linked(graph):
    test_add = _node(graph, "test_calc.test_add")
    add = _node(graph, "calc.add")
    assert test_add is not None and test_add.kind == "test"
    tests_edges = {(e.source, e.target) for e in _edges(graph, EdgeKind.TESTS)}
    assert (test_add.id, add.id) in tests_edges


def test_absolute_import_resolves(graph):
    add = _node(graph, "calc.add")
    test_mod = _node(graph, "test_calc")
    imports = {(e.source, e.target) for e in _edges(graph, EdgeKind.IMPORTS)}
    assert (test_mod.id, add.id) in imports


def test_docstring_code_fence_becomes_example(graph):
    examples = [n for n in graph.nodes if n.kind == "example"]
    assert len(examples) == 1
    example = examples[0]
    assert "add(2, 3)" in example.metadata.get("code", "")
    add = _node(graph, "calc.add")
    exemplifies = {
        (e.source, e.target) for e in _edges(graph, EdgeKind.EXEMPLIFIES)
    }
    assert (example.id, add.id) in exemplifies
