"""The graph store is read in batches, not one row at a time.

``outline`` walked 75 modules with 1312 separate ``SELECT ... WHERE id = ?``
round trips, one per node, because every helper loaded its children
individually. The rows were always known up front.

Kind filtering had the same shape of bug in reverse: recall fetched a fixed
number of rows and then dropped the wrong kinds in Python, so a query whose
matches were mostly some other kind returned fewer results than exist.
"""

from __future__ import annotations

import pytest

from molmcp.discovery.schema import CodeGraph, Edge, EdgeKind, Node, NodeKind
from molmcp.discovery.store import GraphStore


def _node(name: str, kind: str = NodeKind.FUNCTION, summary: str = "") -> Node:
    return Node(
        id=f"m.py#{name}#{kind}",
        kind=kind,
        name=name,
        qualname=f"m.{name}",
        language="python",
        file="m.py",
        start_line=1,
        end_line=2,
        summary=summary,
    )


@pytest.fixture
def store(tmp_path):
    graph = CodeGraph()
    module = Node(
        id="m.py#m#module",
        kind=NodeKind.MODULE,
        name="m",
        qualname="m",
        language="python",
        file="m.py",
        start_line=1,
        end_line=99,
    )
    graph.nodes.append(module)
    for i in range(40):
        child = _node(f"fn{i}", summary="reads a frame")
        graph.nodes.append(child)
        graph.edges.append(
            Edge(source=module.id, target=child.id, kind=EdgeKind.CONTAINS)
        )
    for i in range(10):
        graph.nodes.append(_node(f"Cls{i}", NodeKind.CLASS, summary="reads a frame"))
    st = GraphStore(tmp_path / "graph.db")
    st.create(graph, meta={"snapshot_id": "s"})
    yield st
    st.close()


class TestBatchNodeLoad:
    def test_get_nodes_returns_every_requested_row(self, store):
        ids = [f"m.py#fn{i}#{NodeKind.FUNCTION}" for i in range(40)]

        found = store.get_nodes(ids)

        assert set(found) == set(ids)

    def test_get_nodes_skips_unknown_ids_without_failing(self, store):
        found = store.get_nodes(["nope", f"m.py#fn0#{NodeKind.FUNCTION}"])

        assert list(found) == [f"m.py#fn0#{NodeKind.FUNCTION}"]

    def test_get_nodes_handles_more_ids_than_sqlite_takes_variables(self, store):
        ids = [f"pad{i}" for i in range(3000)]
        ids.append(f"m.py#fn0#{NodeKind.FUNCTION}")

        found = store.get_nodes(ids)

        assert list(found) == [f"m.py#fn0#{NodeKind.FUNCTION}"]

    def test_empty_request_touches_the_database_not_at_all(self, store):
        assert store.get_nodes([]) == {}


class TestOutlineIsBatched:
    def test_outline_does_not_read_one_node_per_query(self, store, monkeypatch):
        from molmcp.discovery.query import DiscoveryQuery

        calls = {"n": 0}
        original = GraphStore.get_node

        def counting(self, node_id):
            calls["n"] += 1
            return original(self, node_id)

        monkeypatch.setattr(GraphStore, "get_node", counting)
        result = DiscoveryQuery(store).outline()

        assert result["module_count"] == 1
        assert len(result["modules"][0]["symbols"]) == 40
        # One round trip per module, not one per contained symbol.
        assert calls["n"] <= 2


class TestKindFilterIsPushedDown:
    def test_a_rare_kind_is_not_starved_by_commoner_matches(self, store):
        """40 functions and 10 classes all match; asking for classes must
        return classes, not whatever survives a fixed-size prefetch."""
        found = store.search("frame", kind=NodeKind.CLASS, limit=10)

        assert len(found) == 10
        assert {n.kind for n in found} == {NodeKind.CLASS}

    def test_an_unfiltered_search_still_returns_the_limit(self, store):
        assert len(store.search("frame", limit=25)) == 25

    def test_a_kind_with_no_matches_returns_empty(self, store):
        assert store.search("frame", kind=NodeKind.ENUM, limit=10) == []
