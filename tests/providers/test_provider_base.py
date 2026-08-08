"""The shared shape every provider plane follows.

Three providers had grown three of everything: three `probe()` bodies, three
missing-package guards worded differently, and three hand-rolled sets of
ToolAnnotations whose values disagreed. `register()` was 70% of each class —
349, 402 and 191 lines — because every tool lived as a nested function inside
it.

A tool is a method with a declaration on it. The base does the registering.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP

from molmcp.providers.annotations import IDEMPOTENT_WRITE, MUTATION, READ_ONLY
from molmcp.providers.base import ProviderBase, tool


class _Fake(ProviderBase):
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    @tool(READ_ONLY)
    def peek(self, item: str = "x") -> dict[str, str]:
        """Look at something."""
        self.calls.append("peek")
        return {"item": item}

    @tool(MUTATION)
    def wreck(self, item: str) -> dict[str, str]:
        """Break something."""
        return {"wrecked": item}

    @tool(IDEMPOTENT_WRITE, name="open")
    def open_thing(self) -> dict[str, bool]:
        """A tool whose wire name is a Python builtin."""
        return {"ok": True}


def _tools(provider: ProviderBase) -> dict:
    mcp = FastMCP(provider.name)
    provider.register(mcp)
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


class TestDeclarationReplacesRegistration:
    def test_every_declared_method_becomes_a_tool(self):
        assert set(_tools(_Fake())) == {"peek", "wreck", "open"}

    def test_a_tool_keeps_its_annotations(self):
        tools = _tools(_Fake())

        assert tools["peek"].annotations.read_only_hint is True
        assert tools["wreck"].annotations.destructive_hint is True

    def test_the_wire_name_can_differ_from_the_method(self):
        """`open` and `exec` are not usable as method names."""
        assert "open" in _tools(_Fake())
        assert "open_thing" not in _tools(_Fake())

    def test_the_docstring_reaches_the_client(self):
        assert "Look at something" in (_tools(_Fake())["peek"].description or "")

    def test_self_is_not_part_of_the_tool_schema(self):
        schema = _tools(_Fake())["peek"].parameters

        assert "self" not in (schema.get("properties") or {})

    def test_a_registered_tool_still_reaches_instance_state(self):
        provider = _Fake()
        mcp = FastMCP(provider.name)
        provider.register(mcp)

        asyncio.run(mcp.call_tool("peek", {"item": "y"}))

        assert provider.calls == ["peek"]

    def test_an_undeclared_method_is_not_registered(self):
        class WithHelper(_Fake):
            def _helper(self) -> str:
                return "not a tool"

        assert "_helper" not in _tools(WithHelper())

    def test_a_subclass_inherits_declared_tools(self):
        class Extended(_Fake):
            @tool(READ_ONLY)
            def extra(self) -> dict[str, bool]:
                """More."""
                return {"ok": True}

        assert set(_tools(Extended())) == {"peek", "wreck", "open", "extra"}


class TestUpstreamGuard:
    def test_a_provider_with_no_upstream_is_always_available(self):
        assert _Fake().probe() is True

    def test_a_missing_upstream_reports_unavailable(self):
        class Absent(_Fake):
            upstream = "molcrafts-nope"
            import_name = "molmcp_nope_xyz"

        assert Absent().probe() is False

    def test_an_installed_upstream_reports_available(self):
        class Present(_Fake):
            upstream = "pytest"
            import_name = "pytest"

        assert Present().probe() is True

    def test_registering_without_the_upstream_says_how_to_install_it(self):
        class Absent(_Fake):
            upstream = "molcrafts-nope"
            import_name = "molmcp_nope_xyz"

        with pytest.raises(RuntimeError) as excinfo:
            Absent().register(FastMCP("fake"))

        message = str(excinfo.value)
        assert "molcrafts-nope" in message
        assert "pip install molcrafts-nope" in message

    def test_probing_never_imports_the_upstream_package(self):
        """A catalog listing must not drag a science stack into the process."""
        import sys

        class Present(_Fake):
            upstream = "molcrafts-thing"
            import_name = "molmcp_probe_probe"

        sys.modules.pop("molmcp_probe_probe", None)
        Present().probe()

        assert "molmcp_probe_probe" not in sys.modules


class TestNamingContract:
    def test_declared_names_are_bare(self):
        """The server name already carries the plane id."""
        from molmcp.middleware import validate_plane_tool_names

        provider = _Fake()
        mcp = FastMCP(provider.name)
        provider.register(mcp)

        assert validate_plane_tool_names(mcp, provider.name) == []

    def test_every_declared_tool_carries_annotations(self):
        from molmcp.middleware import validate_tool_annotations

        provider = _Fake()
        mcp = FastMCP(provider.name)
        provider.register(mcp)

        assert validate_tool_annotations(mcp, strict=False) == []


class TestAnnotationVocabulary:
    @pytest.mark.parametrize("constant", [READ_ONLY, MUTATION, IDEMPOTENT_WRITE])
    def test_each_constant_states_both_required_hints(self, constant):
        assert constant.read_only_hint is not None
        assert constant.destructive_hint is not None

    def test_a_read_is_not_destructive(self):
        assert READ_ONLY.read_only_hint is True
        assert READ_ONLY.destructive_hint is False

    def test_a_mutation_is_flagged_for_confirmation(self):
        assert MUTATION.read_only_hint is False
        assert MUTATION.destructive_hint is True
        assert MUTATION.idempotent_hint is False

    def test_a_scaffold_writes_without_destroying(self):
        assert IDEMPOTENT_WRITE.read_only_hint is False
        assert IDEMPOTENT_WRITE.destructive_hint is False
        assert IDEMPOTENT_WRITE.idempotent_hint is True

    def test_open_world_is_always_stated(self):
        """A client cannot tell 'local' from 'unset' if the hint is absent."""
        for constant in (READ_ONLY, MUTATION, IDEMPOTENT_WRITE):
            assert constant.open_world_hint is not None
