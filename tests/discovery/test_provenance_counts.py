"""Provenance-filtered caller counting.

The ranking relevance signal must not be bought by guessed (heuristic) call
edges — only resolved edges count as callers. This is the structural guard
that a fabricated sink can never again inflate its way to rank 1.
"""

from __future__ import annotations

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


def _fn(name: str) -> Node:
    return Node(
        id=f"m.py#m.{name}#function",
        kind=NodeKind.FUNCTION,
        name=name,
        qualname=f"m.{name}",
        language="python",
        file="m.py",
        start_line=1,
        end_line=2,
    )


def _calls(source: Node, target: Node, provenance: str) -> Edge:
    return Edge(
        source=source.id,
        target=target.id,
        kind=EdgeKind.CALLS,
        provenance=provenance,
        file="m.py",
    )


def _store(tmp_path) -> GraphStore:
    target, resolved_caller, guessed_caller = _fn("hub"), _fn("real"), _fn("guess")
    graph = CodeGraph(
        nodes=[target, resolved_caller, guessed_caller],
        edges=[
            _calls(resolved_caller, target, Provenance.RESOLVED),
            _calls(guessed_caller, target, Provenance.HEURISTIC),
        ],
    )
    store = GraphStore(tmp_path / "graph.db")
    store.create(graph, meta={"schema_version": 1})
    return store


def test_incoming_edge_counts_can_filter_by_provenance(tmp_path):
    store = _store(tmp_path)
    hub = "m.py#m.hub#function"

    unfiltered = store.incoming_edge_counts([hub], EdgeKind.CALLS)
    assert unfiltered == {hub: 2}

    resolved_only = store.incoming_edge_counts(
        [hub], EdgeKind.CALLS, provenance=Provenance.RESOLVED
    )
    assert resolved_only == {hub: 1}


def test_query_caller_counts_exclude_heuristic_edges(tmp_path):
    """ac-002: a node whose only extra callers are heuristic contributes 0
    beyond its resolved callers — the ranking signal is heuristic-proof."""
    query = DiscoveryQuery(_store(tmp_path))
    counts = query.caller_counts(["m.py#m.hub#function"])
    assert counts == {"m.py#m.hub#function": 1}
