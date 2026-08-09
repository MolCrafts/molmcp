"""Unit tests for the pure ranking module (graph-signal reranking)."""

from __future__ import annotations

import pytest

from molmcp.discovery.ranking import (
    KIND_PRIOR,
    W_CALLERS,
    W_EXAMPLE,
    W_EXPORTED,
    W_FTS,
    W_TEST,
    RankCandidate,
    rank_matches,
    rank_signals,
)
from molmcp.discovery.schema import Node, NodeKind, Visibility, node_id

_SIGNAL_KEYS = {
    "fts_rank",
    "is_exported",
    "caller_count",
    "example_count",
    "test_count",
    "kind_prior",
    "score",
}


def _node(
    name: str,
    kind: NodeKind,
    *,
    is_exported: bool = False,
    visibility: Visibility = Visibility.PUBLIC,
) -> Node:
    qualname = f"pkg.{name}"
    return Node(
        id=node_id("pkg/mod.py", qualname, str(kind)),
        kind=str(kind),
        name=name,
        qualname=qualname,
        language="python",
        file="pkg/mod.py",
        start_line=1,
        end_line=2,
        visibility=str(visibility),
        is_exported=is_exported,
    )


def _private_constant(fts_rank: int) -> RankCandidate:
    return RankCandidate(
        node=_node("LIMIT", NodeKind.CONSTANT, visibility=Visibility.PRIVATE),
        fts_rank=fts_rank,
    )


def _exported_class(fts_rank: int) -> RankCandidate:
    return RankCandidate(
        node=_node("Engine", NodeKind.CLASS, is_exported=True),
        fts_rank=fts_rank,
        caller_count=5,
        example_count=1,
        test_count=2,
    )


# -- contract basics ---------------------------------------------------


def test_weight_constants_contract():
    assert all(w > 0 for w in (W_EXPORTED, W_CALLERS, W_EXAMPLE, W_TEST, W_FTS))
    assert min(KIND_PRIOR[k] for k in ("class", "function", "method")) >= 0.9
    assert max(KIND_PRIOR["field"], KIND_PRIOR["constant"]) <= 0.4


def test_rank_signals_has_all_documented_keys():
    cand = RankCandidate(node=_node("add", NodeKind.FUNCTION), fts_rank=0)
    signals = rank_signals(cand)
    assert _SIGNAL_KEYS <= set(signals)
    assert isinstance(signals["score"], float)


# -- happy path (acceptance ac-002) ------------------------------------


def test_exported_called_tested_symbol_outranks_private_constant():
    """ac-002: graph signals beat a private uncalled symbol that sits at
    an equal-or-better FTS recall position."""
    constant = _private_constant(fts_rank=0)
    cls = _exported_class(fts_rank=1)
    ranked = rank_matches([constant, cls])
    assert [c.node.name for c in ranked] == ["Engine", "LIMIT"]


# -- edge cases ---------------------------------------------------------


def test_rank_matches_empty_input_returns_empty_list():
    assert rank_matches([]) == []


def test_rank_matches_single_candidate_returned_as_is():
    cand = RankCandidate(node=_node("add", NodeKind.FUNCTION), fts_rank=0)
    assert rank_matches([cand]) == [cand]


# -- tie-break stability -------------------------------------------------


def test_tied_scores_keep_fts_recall_order():
    first = RankCandidate(node=_node("alpha", NodeKind.FUNCTION), fts_rank=3)
    second = RankCandidate(node=_node("beta", NodeKind.FUNCTION), fts_rank=3)
    ranked = rank_matches([first, second])
    assert ranked == [first, second]


# -- immutability ---------------------------------------------------------


def test_rank_matches_does_not_mutate_input_list():
    constant = _private_constant(fts_rank=0)
    cls = _exported_class(fts_rank=1)
    candidates = [constant, cls]
    snapshot = list(candidates)
    ranked = rank_matches(candidates)
    assert candidates == snapshot
    assert ranked is not candidates


# -- signal behaviour ------------------------------------------------------


def test_score_increases_with_caller_count():
    fewer = RankCandidate(
        node=_node("run", NodeKind.FUNCTION), fts_rank=2, caller_count=1
    )
    more = RankCandidate(
        node=_node("run", NodeKind.FUNCTION), fts_rank=2, caller_count=4
    )
    assert rank_signals(more)["score"] > rank_signals(fewer)["score"]


def test_kind_prior_function_outranks_constant_all_else_equal():
    fn = RankCandidate(node=_node("scale", NodeKind.FUNCTION), fts_rank=0)
    const = RankCandidate(node=_node("SCALE", NodeKind.CONSTANT), fts_rank=0)
    ranked = rank_matches([const, fn])
    assert ranked[0] is fn


class TestNavigationalKindsAreNotAnswers:
    """A module is a container you browse, not a capability entry point.

    KIND_PRIOR had no entry for one, so it took the 0.5 default — and every
    module is importable, so it also collected the full export bonus. On the
    golden fixture that put `readers.top` above `read_gromacs_top` for "read
    a gromacs topology file": the top answer was the file to look in, not
    the function to call.
    """

    def _score(self, kind: str, fts_rank: int = 0, exported: bool = True) -> float:
        node = _node("thing", kind)
        node.is_exported = exported
        return rank_signals(RankCandidate(node=node, fts_rank=fts_rank))["score"]

    @pytest.mark.parametrize(
        "kind", [NodeKind.MODULE, NodeKind.PACKAGE, NodeKind.NAMESPACE]
    )
    def test_a_navigational_kind_scores_below_a_callable(self, kind):
        assert self._score(kind) < self._score(NodeKind.FUNCTION)

    @pytest.mark.parametrize(
        "kind", [NodeKind.MODULE, NodeKind.PACKAGE, NodeKind.NAMESPACE]
    )
    def test_being_importable_earns_a_module_nothing(self, kind):
        """Every module is exported; the flag carries no information here."""
        assert self._score(kind, exported=True) == self._score(kind, exported=False)

    def test_a_symbol_still_earns_its_export_bonus(self):
        assert self._score(NodeKind.FUNCTION, exported=True) > self._score(
            NodeKind.FUNCTION, exported=False
        )

    def test_a_module_at_rank_zero_loses_to_a_function_two_places_back(self):
        """The exact shape the golden fixture hit."""
        assert self._score(NodeKind.MODULE, fts_rank=0) < self._score(
            NodeKind.FUNCTION, fts_rank=2
        )
