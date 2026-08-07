"""Signal re-ranking for capability search.

Recall — the first-pass full-text search (FTS) over indexed symbols —
produces candidates; this module re-orders them. The primary signal is
retrieval quality: ``fts_rank`` is a *field-weighted* lexical position
(a hit in the symbol name outweighs one in a docstring; see the bm25
weights in ``graphstore.search``). Reliable structural signals refine
it: resolved-only caller count, example/test coverage, export status,
and a per-kind prior.

``caller_count`` is fed from RESOLVED call edges only (see
``DiscoveryQuery.caller_counts``): a guessed edge must never buy a symbol
rank, so no unfiltered graph-degree reaches the score. Pure functions: no
SQLite, no MCP (Model Context Protocol) imports. Weights are module
constants so every ranking decision stays inspectable, and
:func:`rank_signals` exposes each feature's value plus the total score.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .schema import Node, NodeKind

# Exported, well-exercised symbols are what an agent should reach for
# first; FTS position still matters but decays instead of dictating
# the order outright.
W_EXPORTED = 1.0
# Resolved callers are supporting evidence, not the main signal — kept low
# so field-weighted lexical relevance leads. Scaled by log1p to damp hubs.
W_CALLERS = 0.3
W_EXAMPLE = 0.8
W_TEST = 0.8
W_FTS = 1.5  # contributes W_FTS / (1 + fts_rank)

# Modules, packages and namespaces are navigational: places to browse, not
# answers to "how do I do this". They used to fall through to the default
# prior *and* collect the full export bonus — every module is importable —
# which on the golden fixture ranked `readers.top` above `read_gromacs_top`
# for "read a gromacs topology file". The reply was the file to look in
# rather than the function to call.
NAVIGATIONAL_KINDS = frozenset({NodeKind.MODULE, NodeKind.PACKAGE, NodeKind.NAMESPACE})

# Containers and callables are likelier capability entry points than
# data members.
KIND_PRIOR: dict[str, float] = {
    NodeKind.MODULE: 0.0,
    NodeKind.PACKAGE: 0.0,
    NodeKind.NAMESPACE: 0.0,
    NodeKind.CLASS: 1.0,
    NodeKind.STRUCT: 1.0,
    NodeKind.INTERFACE: 1.0,
    NodeKind.TRAIT: 1.0,
    NodeKind.FUNCTION: 1.0,
    NodeKind.ENUM: 0.9,
    NodeKind.METHOD: 0.9,
    NodeKind.PROPERTY: 0.5,
    NodeKind.TYPE_ALIAS: 0.4,
    NodeKind.CONSTANT: 0.3,
    NodeKind.FIELD: 0.3,
}
_DEFAULT_PRIOR = 0.5


@dataclass(frozen=True, slots=True)
class RankCandidate:
    """One recall hit plus the graph signals used to re-rank it.

    ``fts_rank`` is the zero-based position in the field-weighted FTS
    result list (0 = best lexical match); ``caller_count`` tallies only
    RESOLVED callers (heuristic edges are excluded upstream), and the
    other counts tally examples and tests referencing ``node``.
    """

    node: Node
    fts_rank: int
    caller_count: int = 0
    example_count: int = 0
    test_count: int = 0


def _score(candidate: RankCandidate) -> float:
    node = candidate.node
    score = W_FTS / (1 + candidate.fts_rank)
    score += KIND_PRIOR.get(node.kind, _DEFAULT_PRIOR)
    # Export status is evidence for a symbol and noise for a container: a
    # module is importable by definition, so the flag distinguishes nothing.
    if node.is_exported and node.kind not in NAVIGATIONAL_KINDS:
        score += W_EXPORTED
    score += W_CALLERS * math.log1p(candidate.caller_count)
    if candidate.example_count > 0:
        score += W_EXAMPLE
    if candidate.test_count > 0:
        score += W_TEST
    return score


def rank_signals(candidate: RankCandidate) -> dict:
    """Explain a candidate's ranking: every feature plus the total."""
    return {
        "fts_rank": candidate.fts_rank,
        "is_exported": candidate.node.is_exported,
        "caller_count": candidate.caller_count,
        "example_count": candidate.example_count,
        "test_count": candidate.test_count,
        "kind_prior": KIND_PRIOR.get(candidate.node.kind, _DEFAULT_PRIOR),
        "score": _score(candidate),
    }


def rank_matches(candidates: Sequence[RankCandidate]) -> list[RankCandidate]:
    """Return a new list sorted by descending score.

    ``sorted`` is stable, so candidates with equal scores keep their
    FTS recall order; the input sequence is never mutated.
    """
    return sorted(candidates, key=_score, reverse=True)
