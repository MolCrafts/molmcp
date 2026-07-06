"""Resolver behaviour on instance-method calls and class instantiation.

Reproduces the ``reader = LammpsDataReader(...); reader.read()`` shape at the
graph level and pins the two defects that poisoned it: the lost constructor
edge (Bug B) and the blind alphabetical sink for unresolved receivers.
"""

from __future__ import annotations

import pytest

from molmcp.discovery.config import DiscoveryConfig
from molmcp.discovery.extract import Extractor
from molmcp.discovery.resolve import Resolver
from molmcp.discovery.schema import CodeGraph, EdgeKind
from molmcp.discovery.source.local import resolve_local_path

from .golden_queries import materialize_fixture


@pytest.fixture
def graph(tmp_path) -> CodeGraph:
    repo = materialize_fixture(tmp_path / "repo")
    snapshot = resolve_local_path(
        repo, str(repo), DiscoveryConfig(cache_dir=tmp_path / "_c")
    )
    return Resolver().resolve(Extractor().extract(snapshot))


def _node(graph: CodeGraph, qualname: str):
    return next((n for n in graph.nodes if n.qualname == qualname), None)


def _call_edges(graph: CodeGraph):
    return [e for e in graph.edges if e.kind == EdgeKind.CALLS]


def test_constructor_call_resolves_to_class(graph):
    """ac-003: instantiating LammpsDataReader produces a resolved CALLS edge
    to the class node (previously dropped because CLASS wasn't callable)."""
    caller = _node(graph, "readers.api.read_lammps_data")
    cls = _node(graph, "readers.lammps.LammpsDataReader")
    assert caller is not None and cls is not None

    edges = [e for e in _call_edges(graph) if e.source == caller.id]
    to_class = [e for e in edges if e.target == cls.id]
    assert to_class, "constructor edge read_lammps_data -> LammpsDataReader missing"
    assert to_class[0].provenance == "resolved"


def test_unresolved_receiver_not_sunk_to_alpha_first(graph):
    """ac-004: reader.read() with an uninferable receiver must NOT be blindly
    attributed to the alphabetically-first read method (AcReader.read)."""
    ac_read = _node(graph, "readers.ac.AcReader.read")
    assert ac_read is not None

    incoming = [e for e in _call_edges(graph) if e.target == ac_read.id]
    legit = _node(graph, "readers.api.read_amber_ac").id  # the one real caller
    foreign_callers = {e.source for e in incoming if e.source != legit}
    # read_lammps_data / read_gromacs_top call reader.read() on OTHER readers;
    # none of those may land on AcReader.read.
    lammps = _node(graph, "readers.api.read_lammps_data")
    gromacs = _node(graph, "readers.api.read_gromacs_top")
    assert lammps.id not in foreign_callers
    assert gromacs.id not in foreign_callers


def test_ambiguous_method_call_left_unresolved(graph):
    """The uninferable reader.read() ref degrades gracefully into
    graph.unresolved rather than being fabricated as a wrong edge."""
    unresolved_read = [r for r in graph.unresolved if r.name.endswith(".read")]
    assert unresolved_read, "expected uninferable .read() refs to stay unresolved"
