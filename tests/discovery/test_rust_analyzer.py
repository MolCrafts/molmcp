from __future__ import annotations

from molmcp.discovery.analyzers.rust import RustAnalyzer
from molmcp.discovery.schema import EdgeKind, FileRecord, NodeKind, Provenance

_SOURCE = """
use crate::geometry::Box3D;

/// A particle in the packed system.
pub struct Particle {
    pub mass: f64,
}

pub trait Measure {
    fn value(&self) -> f64;
}

impl Particle {
    pub fn new(mass: f64) -> Self {
        validate_mass(mass);
        Self { mass }
    }
}

pub fn validate_mass(mass: f64) -> bool {
    mass > 0.0
}
"""


def _analyze():
    file = FileRecord(
        path="src/lib.rs",
        language="rust",
        content_hash="x",
        size=len(_SOURCE),
    )
    return RustAnalyzer().analyze(file, _SOURCE)


def test_rust_extracts_public_types_functions_and_methods():
    result = _analyze()
    assert result.errors == []
    by_name = {node.name: node for node in result.nodes}
    assert by_name["Particle"].kind == NodeKind.STRUCT
    assert by_name["Particle"].is_exported is True
    assert by_name["Measure"].kind == NodeKind.TRAIT
    assert by_name["new"].kind == NodeKind.METHOD
    assert by_name["validate_mass"].kind == NodeKind.FUNCTION
    assert "mass: f64" in (by_name["new"].signature or "")


def test_rust_edges_and_refs_keep_tree_sitter_provenance():
    result = _analyze()
    contains = [edge for edge in result.edges if edge.kind == EdgeKind.CONTAINS]
    assert contains
    assert all(edge.provenance == Provenance.TREE_SITTER for edge in contains)
    refs = {(ref.kind, ref.name) for ref in result.unresolved}
    assert any(kind == EdgeKind.IMPORTS and "geometry" in name for kind, name in refs)
    assert any(
        kind == EdgeKind.CALLS and "validate_mass" in name for kind, name in refs
    )
