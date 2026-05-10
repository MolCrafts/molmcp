"""Tests for the 7 introspection tools registered by IntrospectionProvider."""

from __future__ import annotations

import pytest  # noqa: F401
from conftest import call


class TestListModules:
    async def test_includes_root(self, server):
        modules = await call(server, "list_modules")
        assert "fixture_pkg" in modules
        assert "fixture_pkg.sub" in modules

    async def test_prefix_filter(self, server):
        modules = await call(server, "list_modules", {"prefix": "fixture_pkg.sub"})
        assert modules == ["fixture_pkg.sub"]

    async def test_no_match(self, server):
        modules = await call(server, "list_modules", {"prefix": "no_such_pkg"})
        assert modules == []


class TestListSymbols:
    async def test_root_module(self, server):
        symbols = await call(server, "list_symbols", {"symbol": "fixture_pkg"})
        assert isinstance(symbols, dict)
        assert "greet" in symbols
        assert "Widget" in symbols

    async def test_bad_module(self, server):
        symbols = await call(server, "list_symbols", {"symbol": "fixture_pkg.no_such"})
        assert "error" in symbols

    async def test_class_lists_method_with_kind_tag(self, server):
        members = await call(server, "list_symbols", {"symbol": "fixture_pkg.Widget"})
        assert "grow" in members
        assert members["grow"].startswith("method —")
        assert "Multiply" in members["grow"]

    async def test_class_lists_classmethod(self, server):
        members = await call(server, "list_symbols", {"symbol": "fixture_pkg.Widget"})
        assert "of_default" in members
        assert members["of_default"].startswith("classmethod —")

    async def test_class_lists_staticmethod(self, server):
        members = await call(server, "list_symbols", {"symbol": "fixture_pkg.Widget"})
        assert "double" in members
        assert members["double"].startswith("staticmethod —")

    async def test_class_lists_property(self, server):
        members = await call(server, "list_symbols", {"symbol": "fixture_pkg.Widget"})
        assert "heavy" in members
        assert members["heavy"].startswith("property —")

    async def test_class_lists_attribute_and_nested_class(self, server):
        members = await call(server, "list_symbols", {"symbol": "fixture_pkg.Widget"})
        assert "DEFAULT_FACTOR" in members
        assert members["DEFAULT_FACTOR"].startswith("attribute")
        assert "Config" in members
        assert members["Config"].startswith("nested_class —")

    async def test_class_skips_dunders_and_inherited(self, server):
        members = await call(server, "list_symbols", {"symbol": "fixture_pkg.Widget"})
        # No leading-underscore names; nothing inherited from object.
        assert all(not n.startswith("_") for n in members)
        assert "__init__" not in members
        assert "__class__" not in members

    async def test_non_module_non_class(self, server):
        result = await call(server, "list_symbols", {"symbol": "fixture_pkg.greet"})
        assert "error" in result


class TestGetSource:
    async def test_class(self, server):
        src = await call(server, "get_source", {"symbol": "fixture_pkg.Widget"})
        assert "class Widget" in src

    async def test_method(self, server):
        src = await call(server, "get_source", {"symbol": "fixture_pkg.Widget.grow"})
        assert "def grow" in src

    async def test_module(self, server):
        src = await call(server, "get_source", {"symbol": "fixture_pkg"})
        assert "Widget" in src

    async def test_not_found(self, server):
        src = await call(server, "get_source", {"symbol": "fixture_pkg.NoSuchClass"})
        assert "not found" in src.lower()


class TestGetDocstring:
    async def test_function(self, server):
        doc = await call(server, "get_docstring", {"symbol": "fixture_pkg.greet"})
        assert "greeting" in doc.lower()

    async def test_class(self, server):
        doc = await call(server, "get_docstring", {"symbol": "fixture_pkg.Widget"})
        assert len(doc) > 5

    async def test_not_found(self, server):
        doc = await call(server, "get_docstring", {"symbol": "fixture_pkg.fake"})
        assert "not found" in doc.lower()


class TestGetSignature:
    async def test_function(self, server):
        sig = await call(server, "get_signature", {"symbol": "fixture_pkg.greet"})
        assert "name" in sig
        assert "str" in sig

    async def test_method(self, server):
        sig = await call(server, "get_signature", {"symbol": "fixture_pkg.Widget.grow"})
        assert "factor" in sig
        assert "self" in sig

    async def test_resolves_pep563_forward_ref(self, server):
        # Widget.grow is declared with `-> "Widget"` under
        # `from __future__ import annotations`; without eval_str the
        # signature would surface the bare string ``'Widget'`` rather
        # than the resolved class name.
        sig = await call(server, "get_signature", {"symbol": "fixture_pkg.Widget.grow"})
        assert "Widget" in sig
        assert "'Widget'" not in sig  # not a quoted forward-ref

    async def test_not_found(self, server):
        sig = await call(server, "get_signature", {"symbol": "fixture_pkg.nope"})
        assert "not found" in sig.lower()


class TestSearchSource:
    async def test_finds_class(self, server):
        hits = await call(server, "search_source", {"query": "class Widget"})
        assert len(hits) >= 1
        assert any("class Widget" in h["text"] for h in hits)

    async def test_respects_prefix(self, server):
        hits = await call(
            server,
            "search_source",
            {"query": "answer", "module_prefix": "fixture_pkg.sub"},
        )
        for h in hits:
            assert h["file"].startswith("fixture_pkg/sub")

    async def test_no_match(self, server):
        hits = await call(server, "search_source", {"query": "xyzzy_impossible_12345"})
        assert hits == []

    async def test_max_results_capped_at_50(self, server):
        hits = await call(
            server, "search_source", {"query": "def", "max_results": 1000}
        )
        assert len(hits) <= 50


class TestReadFile:
    async def test_reads_known_file(self, server):
        text = await call(
            server, "read_file", {"relative_path": "fixture_pkg/__init__.py"}
        )
        assert "Widget" in text

    async def test_line_range(self, server):
        text = await call(
            server,
            "read_file",
            {"relative_path": "fixture_pkg/__init__.py", "start": 1, "end": 1},
        )
        assert "\n" not in text

    async def test_rejects_traversal(self, server):
        # PathSafetyMiddleware blocks traversal at the request boundary, surfacing
        # the rejection as a ToolError before read_file's own check runs.
        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="traversal"):
            await call(
                server,
                "read_file",
                {"relative_path": "../../../etc/passwd"},
            )

    async def test_missing_file(self, server):
        text = await call(
            server,
            "read_file",
            {"relative_path": "fixture_pkg/no_such.py"},
        )
        assert "not found" in text.lower()


class TestServerSurface:
    async def test_lists_seven_introspection_tools(self, server):
        tools = await server.list_tools()
        names = {t.name for t in tools}
        expected = {
            "list_modules",
            "list_symbols",
            "get_source",
            "get_docstring",
            "get_signature",
            "search_source",
            "read_file",
        }
        assert expected <= names

    async def test_all_tools_have_readonly_annotation(self, server):
        tools = await server.list_tools()
        for tool in tools:
            ann = tool.annotations
            assert ann is not None, f"{tool.name} missing annotations"
            assert ann.readOnlyHint is True, f"{tool.name} not marked readOnlyHint"
