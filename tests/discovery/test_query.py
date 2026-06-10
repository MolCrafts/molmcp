"""DiscoveryQuery tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine, DiscoveryQuery
from molmcp.discovery.schema import EdgeKind

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
def query(tmp_path) -> DiscoveryQuery:
    repo = tmp_path / "repo"
    _write(repo / "calc.py", _CALC)
    _write(repo / "test_calc.py", _TEST_CALC)
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    return engine.query(str(repo))


def _quals(nodes) -> set[str]:
    return {n.qualname for n in nodes}


def test_search_finds_symbols(query):
    hits = query.search("calculator", limit=10)
    assert "calc.Calc" in _quals(hits) or "calc" in _quals(hits)


def test_search_kind_filter(query):
    hits = query.search("calc", kind="class", limit=10)
    assert hits
    assert all(n.kind == "class" for n in hits)


def test_get_node_prefers_primary_kind(query):
    node = query.get_node("calc.Calc")
    assert node is not None
    assert node.kind == "class"


def test_callers(query):
    callers = _quals(query.callers("calc.add"))
    assert "calc.mul" in callers
    assert "calc.Calc.run" in callers


def test_callees(query):
    callees = _quals(query.callees("calc.mul"))
    assert "calc.add" in callees


def test_implementers(query):
    impl = _quals(query.implementers("calc.Base"))
    assert impl == {"calc.Calc"}


def test_examples_of(query):
    examples = query.examples_of("calc.add")
    assert len(examples) == 1
    assert examples[0].kind == "example"


def test_tests_of(query):
    tests = _quals(query.tests_of("calc.add"))
    assert "test_calc.test_add" in tests


def test_outline(query):
    outline = query.outline()
    modules = {m["qualname"] for m in outline["modules"]}
    assert "calc" in modules
    calc = next(m for m in outline["modules"] if m["qualname"] == "calc")
    symbols = {s["name"] for s in calc["symbols"]}
    assert {"add", "mul", "Base", "Calc"} <= symbols
    calc_class = next(s for s in calc["symbols"] if s["name"] == "Calc")
    assert any(m["name"] == "run" for m in calc_class["members"])


def test_outline_path_filter(query):
    outline = query.outline(path="calc.py")
    assert {m["qualname"] for m in outline["modules"]} == {"calc"}


def test_unknown_symbol_returns_empty(query):
    assert query.get_node("calc.nonexistent") is None
    assert query.callers("calc.nonexistent") == []


# -- batched incoming-edge / caller counts ------------------------------


def _ids(query: DiscoveryQuery, *qualnames: str) -> list[str]:
    out: list[str] = []
    for qualname in qualnames:
        node = query.get_node(qualname)
        assert node is not None
        out.append(node.id)
    return out


def test_incoming_edge_counts_batched(query):
    add_id, mul_id, base_id = _ids(query, "calc.add", "calc.mul", "calc.Base")
    counts = query.store.incoming_edge_counts([add_id, mul_id, base_id], EdgeKind.CALLS)
    # add is called by mul, Calc.run and test_add; mul by Calc.run;
    # Base has zero CALLS in-edges and must be absent from the result.
    assert counts == {add_id: 3, mul_id: 1}


def test_incoming_edge_counts_empty_input(query):
    assert query.store.incoming_edge_counts([], EdgeKind.CALLS) == {}


def test_incoming_edge_counts_only_requested_kind(query):
    (add_id,) = _ids(query, "calc.add")
    # test_add both CALLS and TESTS calc.add; kinds must not bleed.
    tests = query.store.incoming_edge_counts([add_id], EdgeKind.TESTS)
    calls = query.store.incoming_edge_counts([add_id], EdgeKind.CALLS)
    assert tests == {add_id: 1}
    assert calls == {add_id: 3}


def test_caller_counts_delegates_to_store(query):
    add_id, base_id = _ids(query, "calc.add", "calc.Base")
    assert query.caller_counts([add_id, base_id]) == {add_id: 3}
