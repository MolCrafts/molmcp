"""PythonAnalyzer extraction tests, run against the in-tree fixture_pkg."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmcp.discovery.analyzers.base import AnalyzerResult
from molmcp.discovery.analyzers.python import PythonAnalyzer
from molmcp.discovery.schema import EdgeKind, FileRecord

_FIXTURE = Path(__file__).parent.parent / "fixture_pkg" / "__init__.py"


@pytest.fixture
def result() -> AnalyzerResult:
    source = _FIXTURE.read_text(encoding="utf-8")
    record = FileRecord(
        path="fixture_pkg/__init__.py",
        language="python",
        content_hash="x",
        size=len(source),
    )
    return PythonAnalyzer().analyze(record, source)


def _by_qualname(result: AnalyzerResult, qualname: str):
    for node in result.nodes:
        if node.qualname == qualname:
            return node
    return None


def test_no_extraction_errors(result):
    assert result.errors == []


def test_module_node_is_package(result):
    module = _by_qualname(result, "fixture_pkg")
    assert module is not None
    assert module.kind == "package"
    assert module.docstring is not None


def test_class_and_function_exported_via_dunder_all(result):
    widget = _by_qualname(result, "fixture_pkg.Widget")
    greet = _by_qualname(result, "fixture_pkg.greet")
    assert widget is not None and widget.kind == "class"
    assert widget.is_exported is True
    assert greet is not None and greet.kind == "function"
    assert greet.is_exported is True
    assert greet.signature is not None and "name" in greet.signature


def test_methods_and_kinds(result):
    grow = _by_qualname(result, "fixture_pkg.Widget.grow")
    of_default = _by_qualname(result, "fixture_pkg.Widget.of_default")
    double = _by_qualname(result, "fixture_pkg.Widget.double")
    heavy = _by_qualname(result, "fixture_pkg.Widget.heavy")

    assert grow is not None and grow.kind == "method"
    assert grow.signature is not None and "factor" in grow.signature
    assert grow.is_exported is False

    assert of_default is not None
    assert any("classmethod" in d for d in of_default.decorators)
    assert of_default.metadata.get("method_type") == "classmethod"

    assert double is not None
    assert double.metadata.get("method_type") == "staticmethod"

    assert heavy is not None and heavy.kind == "property"


def test_nested_class_and_field(result):
    config = _by_qualname(result, "fixture_pkg.Widget.Config")
    factor = _by_qualname(result, "fixture_pkg.Widget.DEFAULT_FACTOR")
    assert config is not None and config.kind == "class"
    assert factor is not None and factor.kind == "field"


def test_contains_edges_link_parents_to_children(result):
    module = _by_qualname(result, "fixture_pkg")
    widget = _by_qualname(result, "fixture_pkg.Widget")
    grow = _by_qualname(result, "fixture_pkg.Widget.grow")
    contains = {
        (e.source, e.target) for e in result.edges if e.kind == EdgeKind.CONTAINS
    }
    assert (module.id, widget.id) in contains
    assert (widget.id, grow.id) in contains


def test_calls_recorded_as_unresolved(result):
    of_default = _by_qualname(result, "fixture_pkg.Widget.of_default")
    call_refs = {
        r.name
        for r in result.unresolved
        if r.kind == EdgeKind.CALLS and r.from_node == of_default.id
    }
    # of_default does `return cls(cls.DEFAULT_FACTOR)`
    assert "cls" in call_refs


def test_syntax_error_is_captured_not_raised():
    record = FileRecord(path="bad.py", language="python", content_hash="x", size=10)
    out = PythonAnalyzer().analyze(record, "def broken(:\n")
    assert out.nodes == []
    assert any("SyntaxError" in e for e in out.errors)


def _analyze(path: str, source: str) -> AnalyzerResult:
    record = FileRecord(
        path=path, language="python", content_hash="x", size=len(source)
    )
    return PythonAnalyzer().analyze(record, source)


def test_overload_stubs_collapse_to_single_node():
    source = (
        "from typing import overload\n"
        "\n"
        "\n"
        "class Box:\n"
        "    @overload\n"
        "    def __getitem__(self, key: int) -> str: ...\n"
        "    @overload\n"
        "    def __getitem__(self, key: slice) -> list[str]: ...\n"
        "    def __getitem__(self, key):\n"
        '        """Real implementation."""\n'
        "        return key\n"
    )
    out = _analyze("box.py", source)
    items = [n for n in out.nodes if n.name == "__getitem__"]
    assert len(items) == 1
    # The surviving node is the implementation, not a stub.
    assert items[0].docstring == "Real implementation."
    assert len({n.id for n in out.nodes}) == len(out.nodes)


def test_module_level_typing_overload_stubs_collapse():
    source = (
        "import typing\n"
        "\n"
        "\n"
        "@typing.overload\n"
        "def pick(key: int) -> str: ...\n"
        "@typing.overload\n"
        "def pick(key: slice) -> list[str]: ...\n"
        "def pick(key):\n"
        "    return key\n"
    )
    out = _analyze("pick.py", source)
    picks = [n for n in out.nodes if n.name == "pick" and n.kind == "function"]
    assert len(picks) == 1
