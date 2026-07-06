"""Deterministic golden-set regression for capability ranking.

The canary: "read a lammps data file" must surface the real LAMMPS reader
first, not the alphabetically-first ``AcReader.read`` sink. Runs the full
``find_capability`` path over a hermetic fixture — no molpy, no network,
no model.
"""

from __future__ import annotations

import pytest

from molmcp.discovery import DiscoveryConfig, DiscoveryEngine
from molmcp.discovery.evidence import EvidenceBuilder

from .golden_queries import GOLDEN, materialize_fixture


@pytest.fixture
def finder(tmp_path):
    repo = materialize_fixture(tmp_path / "repo")
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    query = engine.query(str(repo))
    return EvidenceBuilder(query)


def _ranked_quals(finder, task: str, k: int) -> list[str]:
    result = finder.find_capability(task, k)
    return [m["node"]["qualname"] for m in result["matches"]]


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["task"])
def test_golden_capability_ranking(finder, case):
    quals = _ranked_quals(finder, case["task"], 5)
    assert quals, f"no matches for {case['task']!r}"

    top1 = quals[0]
    assert any(top1.endswith(s) for s in case["expect_top1_suffixes"]), (
        f"{case['task']!r}: rank-1 was {top1!r}, "
        f"expected one of {case['expect_top1_suffixes']}"
    )

    top3 = quals[:3]
    for forbidden in case["forbid_top3_suffixes"]:
        assert not any(q.endswith(forbidden) for q in top3), (
            f"{case['task']!r}: {forbidden!r} must not be in top-3, got {top3}"
        )


def test_relations_expose_provenance(tmp_path):
    """ac-005: the call graph survives as a provenance-labeled feature.

    Ranking no longer consumes it, but relations() still return edges and
    every edge carries a provenance label distinguishing resolved from
    guessed.
    """
    repo = materialize_fixture(tmp_path / "repo")
    engine = DiscoveryEngine(DiscoveryConfig(cache_dir=tmp_path / "cache"))
    query = engine.query(str(repo))

    callees = query.callees_pairs("readers.api.read_lammps_data")
    assert callees, "call graph feature should still return callees"
    for _node, edge in callees:
        assert str(edge.provenance) in {"resolved", "heuristic"}
