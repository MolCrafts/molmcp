"""Unit tests for lint_graph over synthetic CodeGraph objects (no SQLite)."""

from __future__ import annotations

import dataclasses
import json
import random

import pytest
from molmcp.discovery.lint import (
    MIN_MODULE_REFS,
    UNRESOLVED_THRESHOLD,
    LintReport,
    ModuleUnresolvedStat,
    lint_graph,
)

from molmcp.discovery.schema import (
    CodeGraph,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Provenance,
    UnresolvedRef,
    Visibility,
    node_id,
)

# ---------------------------------------------------------------------------
# Synthetic-graph helpers
# ---------------------------------------------------------------------------


def _symbol(
    qualname: str,
    *,
    kind: str = NodeKind.FUNCTION,
    file: str = "pkg/mod.py",
    start_line: int = 1,
    docstring: str | None = None,
    summary: str | None = None,
    visibility: str = Visibility.PUBLIC,
    is_exported: bool = False,
) -> Node:
    """Build a Node with discovery-realistic defaults."""
    return Node(
        id=node_id(file, qualname, str(kind)),
        kind=kind,
        name=qualname.rsplit(".", 1)[-1],
        qualname=qualname,
        language="python",
        file=file,
        start_line=start_line,
        end_line=start_line + 1,
        docstring=docstring,
        summary=summary,
        visibility=visibility,
        is_exported=is_exported,
    )


def _tests_edge(target: Node) -> Edge:
    """An incoming TESTS edge for *target* from a synthetic test function."""
    return Edge(
        source=node_id("tests/test_mod.py", "test_target", str(NodeKind.FUNCTION)),
        target=target.id,
        kind=EdgeKind.TESTS,
        provenance=Provenance.HEURISTIC,
        file="tests/test_mod.py",
        line=1,
    )


def _unresolved_refs(file: str, count: int) -> list[UnresolvedRef]:
    return [
        UnresolvedRef(
            from_node=node_id(file, "mod", str(NodeKind.MODULE)),
            name=f"missing_{i}",
            kind=EdgeKind.CALLS,
            file=file,
            line=i + 1,
        )
        for i in range(count)
    ]


def _resolved_edges(file: str, count: int) -> list[Edge]:
    return [
        Edge(
            source=node_id(file, "mod", str(NodeKind.MODULE)),
            target=node_id("pkg/other.py", f"hit_{i}", str(NodeKind.FUNCTION)),
            kind=EdgeKind.REFERENCES,
            provenance=Provenance.RESOLVED,
            file=file,
            line=i + 1,
        )
        for i in range(count)
    ]


def _ast_edges(file: str, count: int) -> list[Edge]:
    return [
        Edge(
            source=node_id(file, "mod", str(NodeKind.MODULE)),
            target=node_id(file, f"local_{i}", str(NodeKind.FUNCTION)),
            kind=EdgeKind.CONTAINS,
            provenance=Provenance.AST,
            file=file,
            line=i + 1,
        )
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Dimension 1 — undocumented exports
# ---------------------------------------------------------------------------


def test_undocumented_exported_symbol_flagged() -> None:
    bare = _symbol("pkg.mod.run", is_exported=True)
    report = lint_graph(CodeGraph(nodes=[bare]))
    assert [n.qualname for n in report.undocumented_exports] == ["pkg.mod.run"]


def test_empty_string_docstring_and_summary_count_as_undocumented() -> None:
    bare = _symbol("pkg.mod.run", is_exported=True, docstring="", summary="")
    report = lint_graph(CodeGraph(nodes=[bare]))
    assert [n.qualname for n in report.undocumented_exports] == ["pkg.mod.run"]


def test_exported_symbol_with_summary_not_flagged() -> None:
    documented = _symbol("pkg.mod.run", is_exported=True, summary="Runs the thing.")
    report = lint_graph(CodeGraph(nodes=[documented]))
    assert report.undocumented_exports == ()


def test_exported_symbol_with_docstring_only_not_flagged() -> None:
    documented = _symbol("pkg.mod.run", is_exported=True, docstring="Runs the thing.")
    report = lint_graph(CodeGraph(nodes=[documented]))
    assert report.undocumented_exports == ()


def test_non_exported_undocumented_symbol_not_flagged() -> None:
    internal = _symbol("pkg.mod.helper", is_exported=False)
    report = lint_graph(CodeGraph(nodes=[internal]))
    assert report.undocumented_exports == ()


def test_undocumented_module_and_package_kinds_not_flagged() -> None:
    module = _symbol("pkg.mod", kind=NodeKind.MODULE, is_exported=True)
    package = _symbol(
        "pkg", kind=NodeKind.PACKAGE, file="pkg/__init__.py", is_exported=True
    )
    report = lint_graph(CodeGraph(nodes=[module, package]))
    assert report.undocumented_exports == ()


# ---------------------------------------------------------------------------
# Dimension 2 — untested public symbols
# ---------------------------------------------------------------------------


def test_public_function_without_tests_edge_flagged() -> None:
    fn = _symbol("pkg.mod.run", summary="Documented.")
    report = lint_graph(CodeGraph(nodes=[fn]))
    assert [n.qualname for n in report.untested_public_symbols] == ["pkg.mod.run"]


def test_public_symbol_with_tests_in_edge_not_flagged() -> None:
    fn = _symbol("pkg.mod.run", summary="Documented.")
    report = lint_graph(CodeGraph(nodes=[fn], edges=[_tests_edge(fn)]))
    assert report.untested_public_symbols == ()


def test_private_untested_function_not_flagged() -> None:
    fn = _symbol("pkg.mod._run", summary="Documented.", visibility=Visibility.PRIVATE)
    report = lint_graph(CodeGraph(nodes=[fn]))
    assert report.untested_public_symbols == ()


def test_untested_method_kind_not_flagged() -> None:
    method = _symbol("pkg.mod.C.run", kind=NodeKind.METHOD, summary="Documented.")
    report = lint_graph(CodeGraph(nodes=[method]))
    assert report.untested_public_symbols == ()


def test_untested_public_class_flagged() -> None:
    cls = _symbol("pkg.mod.Engine", kind=NodeKind.CLASS, summary="Documented.")
    report = lint_graph(CodeGraph(nodes=[cls]))
    assert [n.qualname for n in report.untested_public_symbols] == ["pkg.mod.Engine"]


# ---------------------------------------------------------------------------
# Dimension 3 — high-unresolved modules
# ---------------------------------------------------------------------------


def test_fully_unresolved_module_flagged_with_correct_stats() -> None:
    count = MIN_MODULE_REFS + 1
    graph = CodeGraph(unresolved=_unresolved_refs("pkg/dark.py", count))
    report = lint_graph(graph)
    assert report.high_unresolved_modules == (
        ModuleUnresolvedStat(
            file="pkg/dark.py",
            unresolved_count=count,
            total_refs=count,
            ratio=1.0,
        ),
    )


def test_module_below_min_refs_not_flagged() -> None:
    count = MIN_MODULE_REFS - 1
    graph = CodeGraph(unresolved=_unresolved_refs("pkg/tiny.py", count))
    report = lint_graph(graph)
    assert report.high_unresolved_modules == ()


def test_ratio_exactly_at_threshold_not_flagged() -> None:
    # 3 unresolved + 3 resolved -> ratio == UNRESOLVED_THRESHOLD exactly.
    assert UNRESOLVED_THRESHOLD == 0.5
    graph = CodeGraph(
        edges=_resolved_edges("pkg/half.py", 3),
        unresolved=_unresolved_refs("pkg/half.py", 3),
    )
    report = lint_graph(graph)
    assert report.high_unresolved_modules == ()


def test_non_resolved_provenance_edges_excluded_from_total_refs() -> None:
    # 3 unresolved + 2 resolved = 5 total (ratio 0.6 -> flagged); the AST
    # edges on the same file must not inflate total_refs.
    graph = CodeGraph(
        edges=_resolved_edges("pkg/mixed.py", 2) + _ast_edges("pkg/mixed.py", 4),
        unresolved=_unresolved_refs("pkg/mixed.py", 3),
    )
    report = lint_graph(graph)
    assert report.high_unresolved_modules == (
        ModuleUnresolvedStat(
            file="pkg/mixed.py",
            unresolved_count=3,
            total_refs=5,
            ratio=0.6,
        ),
    )


# ---------------------------------------------------------------------------
# Empty graph
# ---------------------------------------------------------------------------


def test_empty_graph_yields_no_findings() -> None:
    report = lint_graph(CodeGraph())
    assert report.undocumented_exports == ()
    assert report.untested_public_symbols == ()
    assert report.high_unresolved_modules == ()
    assert report.total_findings == 0


# ---------------------------------------------------------------------------
# Report shape and immutability
# ---------------------------------------------------------------------------


def _graph_with_one_finding_per_dimension() -> CodeGraph:
    bare = _symbol("pkg.mod.run", is_exported=True)
    return CodeGraph(
        nodes=[bare],
        unresolved=_unresolved_refs("pkg/dark.py", MIN_MODULE_REFS + 1),
    )


def test_report_fields_are_tuples() -> None:
    report = lint_graph(_graph_with_one_finding_per_dimension())
    assert isinstance(report.undocumented_exports, tuple)
    assert isinstance(report.untested_public_symbols, tuple)
    assert isinstance(report.high_unresolved_modules, tuple)


def test_total_findings_sums_all_three_dimensions() -> None:
    report = lint_graph(_graph_with_one_finding_per_dimension())
    expected = (
        len(report.undocumented_exports)
        + len(report.untested_public_symbols)
        + len(report.high_unresolved_modules)
    )
    assert report.total_findings == expected
    assert report.total_findings == 3


def test_lint_report_is_frozen() -> None:
    report = lint_graph(CodeGraph())
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.undocumented_exports = ()  # type: ignore[misc]


def test_module_unresolved_stat_is_frozen() -> None:
    stat = ModuleUnresolvedStat(
        file="a.py", unresolved_count=6, total_refs=6, ratio=1.0
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        stat.ratio = 0.0  # type: ignore[misc]


def test_to_dict_is_json_serializable_with_documented_keys() -> None:
    report = lint_graph(_graph_with_one_finding_per_dimension())
    payload = report.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload) >= {
        "undocumented_exports",
        "untested_public_symbols",
        "high_unresolved_modules",
        "summary",
    }
    entry = payload["undocumented_exports"][0]
    assert entry["qualname"] == "pkg.mod.run"
    assert {"qualname", "kind", "file", "start_line"} <= set(entry)


def test_to_dict_summary_counts_match_report() -> None:
    report = lint_graph(_graph_with_one_finding_per_dimension())
    summary = report.to_dict()["summary"]
    assert summary["undocumented_exports"] == len(report.undocumented_exports)
    assert summary["untested_public_symbols"] == len(report.untested_public_symbols)
    assert summary["high_unresolved_modules"] == len(report.high_unresolved_modules)


def test_lint_report_type_is_returned() -> None:
    assert isinstance(lint_graph(CodeGraph()), LintReport)


# ---------------------------------------------------------------------------
# Determinism — sorted output regardless of insertion order
# ---------------------------------------------------------------------------


def test_undocumented_exports_sorted_by_file_and_start_line() -> None:
    nodes = [
        _symbol("a.early", file="a.py", start_line=1, is_exported=True),
        _symbol("a.late", file="a.py", start_line=5, is_exported=True),
        _symbol("b.mid", file="b.py", start_line=10, is_exported=True),
        _symbol("c.solo", file="c.py", start_line=2, is_exported=True),
    ]
    random.Random(42).shuffle(nodes)
    report = lint_graph(CodeGraph(nodes=nodes))
    assert [(n.file, n.start_line) for n in report.undocumented_exports] == [
        ("a.py", 1),
        ("a.py", 5),
        ("b.py", 10),
        ("c.py", 2),
    ]


def test_untested_public_symbols_sorted_by_file_and_start_line() -> None:
    nodes = [
        _symbol("b.run", file="b.py", start_line=3, summary="Doc."),
        _symbol("a.late", file="a.py", start_line=9, summary="Doc."),
        _symbol("a.early", file="a.py", start_line=2, summary="Doc."),
    ]
    random.Random(7).shuffle(nodes)
    report = lint_graph(CodeGraph(nodes=nodes))
    assert [(n.file, n.start_line) for n in report.untested_public_symbols] == [
        ("a.py", 2),
        ("a.py", 9),
        ("b.py", 3),
    ]


def test_high_unresolved_modules_sorted_by_file() -> None:
    count = MIN_MODULE_REFS + 1
    graph = CodeGraph(
        unresolved=_unresolved_refs("z.py", count) + _unresolved_refs("a.py", count),
    )
    report = lint_graph(graph)
    assert [stat.file for stat in report.high_unresolved_modules] == ["a.py", "z.py"]
