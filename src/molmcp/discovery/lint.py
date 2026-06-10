"""Discoverability lint — measure a graph's search-readiness.

molmcp does not enforce upstream coding discipline; this module only
measures it. The report names symbols invisible to full-text search
(no docstring/summary), public symbols with no linked tests, and
modules whose references mostly failed to resolve — feedback the
source repos can act on to improve discovery quality.

Pure functions over an in-memory :class:`CodeGraph`: no SQLite, no
GraphStore, no MCP. The CLI (``molmcp discovery lint``) is a thin
renderer on top.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .schema import CodeGraph, EdgeKind, Node, NodeKind, Provenance, Visibility

# A module is only judged once it has enough references to be
# meaningful (avoids 1/1 = 100% noise); the ratio must strictly
# exceed the threshold to be reported.
UNRESOLVED_THRESHOLD = 0.5
MIN_MODULE_REFS = 5

# Structural kinds carry no API surface of their own — an undocumented
# package/module is a different (out-of-scope) problem.
_STRUCTURAL_KINDS = {
    NodeKind.FILE,
    NodeKind.PACKAGE,
    NodeKind.MODULE,
    NodeKind.IMPORT,
    NodeKind.EXPORT,
}
# First version only attributes direct TESTS in-edges, and only to the
# kinds tests usually target.
_TESTABLE_KINDS = {NodeKind.CLASS, NodeKind.FUNCTION}


@dataclass(frozen=True)
class ModuleUnresolvedStat:
    """Unresolved-reference share for one source file.

    A reference is *unresolved* when the analyzer could not link it to a
    definition in the graph. ``ratio`` is ``unresolved_count / total_refs``,
    where ``total_refs`` counts resolved and unresolved references alike.
    """

    file: str
    unresolved_count: int
    total_refs: int
    ratio: float

    def to_dict(self) -> dict:
        """JSON-ready dict mirroring the field names."""
        return {
            "file": self.file,
            "unresolved_count": self.unresolved_count,
            "total_refs": self.total_refs,
            "ratio": self.ratio,
        }


def _symbol_entry(node: Node) -> dict:
    return {
        "qualname": node.qualname,
        "kind": str(node.kind),
        "file": node.file,
        "start_line": node.start_line,
    }


@dataclass(frozen=True)
class LintReport:
    """Immutable result of one :func:`lint_graph` run."""

    undocumented_exports: tuple[Node, ...]
    untested_public_symbols: tuple[Node, ...]
    high_unresolved_modules: tuple[ModuleUnresolvedStat, ...]

    @property
    def total_findings(self) -> int:
        """Finding count summed across all three categories."""
        return (
            len(self.undocumented_exports)
            + len(self.untested_public_symbols)
            + len(self.high_unresolved_modules)
        )

    def to_dict(self) -> dict:
        """JSON-ready dict: counts under ``"summary"``, listings after."""
        return {
            "summary": {
                "undocumented_exports": len(self.undocumented_exports),
                "untested_public_symbols": len(self.untested_public_symbols),
                "high_unresolved_modules": len(self.high_unresolved_modules),
            },
            "undocumented_exports": [
                _symbol_entry(n) for n in self.undocumented_exports
            ],
            "untested_public_symbols": [
                _symbol_entry(n) for n in self.untested_public_symbols
            ],
            "high_unresolved_modules": [
                s.to_dict() for s in self.high_unresolved_modules
            ],
        }


def _position(node: Node) -> tuple[str, int]:
    return (node.file, node.start_line)


def lint_graph(graph: CodeGraph) -> LintReport:
    """Scan a graph for discoverability findings (single pass, sorted)."""
    tested_ids = {e.target for e in graph.edges if e.kind == EdgeKind.TESTS}
    undocumented = sorted(
        (
            n
            for n in graph.nodes
            if n.is_exported
            and not n.docstring
            and not n.summary
            and n.kind not in _STRUCTURAL_KINDS
        ),
        key=_position,
    )
    untested = sorted(
        (
            n
            for n in graph.nodes
            if n.kind in _TESTABLE_KINDS
            and n.visibility == Visibility.PUBLIC
            and n.id not in tested_ids
        ),
        key=_position,
    )

    unresolved_by_file: dict[str, int] = defaultdict(int)
    for ref in graph.unresolved:
        if ref.file:
            unresolved_by_file[ref.file] += 1
    resolved_by_file: dict[str, int] = defaultdict(int)
    for edge in graph.edges:
        if edge.file and edge.provenance == Provenance.RESOLVED:
            resolved_by_file[edge.file] += 1
    stats = []
    for file, unresolved_count in unresolved_by_file.items():
        total_refs = unresolved_count + resolved_by_file.get(file, 0)
        if total_refs < MIN_MODULE_REFS:
            continue
        ratio = unresolved_count / total_refs
        if ratio > UNRESOLVED_THRESHOLD:
            stats.append(
                ModuleUnresolvedStat(file, unresolved_count, total_refs, ratio)
            )
    stats.sort(key=lambda s: s.file)

    return LintReport(
        undocumented_exports=tuple(undocumented),
        untested_public_symbols=tuple(untested),
        high_unresolved_modules=tuple(stats),
    )
