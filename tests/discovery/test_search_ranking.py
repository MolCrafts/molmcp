"""Recall is bm25; the order handed back is bm25 *refined by signals*.

`ranking.py` computed export status, resolved-caller count, example and test
coverage, and a per-kind prior — and nothing on the path an MCP tool takes
ever called it. `search` returned raw lexical order and the documented
"spine" had no effect on anything an agent saw.

Refinement happens inside a source's own query, because RRF is a fusion
over already-ranked lists: improving each input list is exactly what it
consumes. That also keeps `collection/` free of discovery internals.
"""

from __future__ import annotations

import pytest

from molmcp.discovery.query import DiscoveryQuery
from molmcp.discovery.schema import (
    CodeGraph,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Provenance,
)
from molmcp.discovery.store import GraphStore


def _fn(name: str, *, exported: bool = False, summary: str = "reads a frame") -> Node:
    return Node(
        id=f"m.py#{name}#{NodeKind.FUNCTION}",
        kind=NodeKind.FUNCTION,
        name=name,
        qualname=f"m.{name}",
        language="python",
        file="m.py",
        start_line=1,
        end_line=2,
        summary=summary,
        is_exported=exported,
    )


@pytest.fixture
def store(tmp_path):
    """Four equally-matching functions that differ only in their signals."""
    graph = CodeGraph()
    plain = _fn("read_frame_plain")
    exported = _fn("read_frame_exported", exported=True)
    tested = _fn("read_frame_tested")
    called = _fn("read_frame_called")
    graph.nodes.extend([plain, exported, tested, called])

    test_node = Node(
        id="t.py#test_it#test",
        kind=NodeKind.TEST,
        name="test_read_frame",
        qualname="t.test_read_frame",
        language="python",
        file="t.py",
        start_line=1,
        end_line=2,
    )
    graph.nodes.append(test_node)
    graph.edges.append(
        Edge(
            source=test_node.id,
            target=tested.id,
            kind=EdgeKind.TESTS,
            provenance=Provenance.HEURISTIC,
        )
    )
    for i in range(5):
        caller = _fn(f"caller{i}", summary="unrelated")
        graph.nodes.append(caller)
        graph.edges.append(
            Edge(
                source=caller.id,
                target=called.id,
                kind=EdgeKind.CALLS,
                provenance=Provenance.RESOLVED,
            )
        )
    st = GraphStore(tmp_path / "graph.db")
    st.create(graph, meta={"snapshot_id": "s"})
    yield st
    st.close()


def _names(nodes) -> list[str]:
    return [n.name for n in nodes]


class TestSignalsReachTheResult:
    """Lexical position still leads — W_FTS is the largest weight — so what
    is pinned here is that signals *refine* it, not that they override it.
    A single signal is deliberately not enough to jump a whole rank."""

    def test_export_status_reorders_otherwise_equal_matches(self, store):
        found = _names(DiscoveryQuery(store).search("frame", limit=5))

        assert found.index("read_frame_exported") < found.index("read_frame_plain")

    def test_the_store_order_is_not_simply_passed_through(self, store):
        raw = _names(store.search("frame", limit=5))
        ranked = _names(DiscoveryQuery(store).search("frame", limit=5))

        assert set(raw) == set(ranked)
        assert raw != ranked

    def test_signals_accumulate_to_overtake_a_lexical_lead(self, tmp_path):
        """One signal does not jump a rank; several together do."""
        graph = CodeGraph()
        first = _fn("read_frame_aaa")
        rich = _fn("read_frame_zzz", exported=True)
        graph.nodes.extend([first, rich])
        example = Node(
            id="m.py#ex#example",
            kind=NodeKind.EXAMPLE,
            name="ex",
            qualname="m.ex",
            language="python",
            file="m.py",
            start_line=1,
            end_line=2,
        )
        covering = Node(
            id="t.py#test_rich#test",
            kind=NodeKind.TEST,
            name="test_rich",
            qualname="t.test_rich",
            language="python",
            file="t.py",
            start_line=1,
            end_line=2,
        )
        graph.nodes.extend([example, covering])
        graph.edges.extend(
            [
                Edge(
                    source=example.id,
                    target=rich.id,
                    kind=EdgeKind.EXEMPLIFIES,
                    provenance=Provenance.HEURISTIC,
                ),
                Edge(
                    source=covering.id,
                    target=rich.id,
                    kind=EdgeKind.TESTS,
                    provenance=Provenance.HEURISTIC,
                ),
            ]
        )
        st = GraphStore(tmp_path / "rich.db")
        st.create(graph, meta={"snapshot_id": "s"})
        try:
            ranked = _names(DiscoveryQuery(st).search("read_frame", limit=2))
        finally:
            st.close()

        # Exported + example + test = 2.6 against a one-rank lexical lead.
        assert ranked[0] == "read_frame_zzz"


class TestRankingStaysCheap:
    def test_signals_are_fetched_in_batches_not_per_candidate(self, store, monkeypatch):
        """Two queries per candidate would undo the batching work."""
        calls = {"n": 0}
        original = GraphStore.incoming_edge_counts

        def counting(self, node_ids, kind, *, provenance=None):
            calls["n"] += 1
            return original(self, node_ids, kind, provenance=provenance)

        monkeypatch.setattr(GraphStore, "incoming_edge_counts", counting)
        DiscoveryQuery(store).search("frame", limit=4)

        # One batched read per signal: callers, examples, tests.
        assert calls["n"] == 3

    def test_no_per_node_edge_walk_happens(self, store, monkeypatch):
        calls = {"n": 0}
        original = GraphStore.edges_to

        def counting(self, node_id, kind=None):
            calls["n"] += 1
            return original(self, node_id, kind)

        monkeypatch.setattr(GraphStore, "edges_to", counting)
        DiscoveryQuery(store).search("frame", limit=4)

        assert calls["n"] == 0


class TestContractsThatMustHold:
    def test_the_limit_is_still_respected(self, store):
        assert len(DiscoveryQuery(store).search("frame", limit=2)) == 2

    def test_the_kind_filter_still_applies(self, store):
        found = DiscoveryQuery(store).search("frame", kind=NodeKind.TEST, limit=5)

        assert {n.kind for n in found} == {NodeKind.TEST}

    def test_a_query_matching_nothing_returns_empty(self, store):
        assert DiscoveryQuery(store).search("zzzznomatch", limit=5) == []

    def test_the_store_still_returns_raw_lexical_order(self, store):
        """Ranking is the query's job; the store stays a recall primitive."""
        raw = _names(store.search("frame", limit=5))

        assert sorted(raw) == sorted(
            [
                "read_frame_plain",
                "read_frame_exported",
                "read_frame_tested",
                "read_frame_called",
                "test_read_frame",
            ]
        )
