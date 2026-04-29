"""Smoke test that the gateway mounts every plugin and exposes their tools."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")
pytest.importorskip("molmcp_molpy", reason="molmcp-molpy not installed")
pytest.importorskip("molmcp_molexp", reason="molmcp-molexp not installed")
pytest.importorskip("molmcp_lammps", reason="molmcp-lammps not installed")


def _list_tool_names(mcp) -> set[str]:
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def test_gateway_imports_with_three_namespaces():
    from molmcp_gateway.config import PLUGIN_NAMESPACES
    from molmcp_gateway.server import mcp

    names = _list_tool_names(mcp)
    assert names, "gateway exposed zero tools"

    for ns in PLUGIN_NAMESPACES:
        prefix = f"{ns}_"
        assert any(n.startswith(prefix) for n in names), (
            f"no tools mounted under namespace {ns!r}: {sorted(names)[:10]}"
        )


def test_gateway_tool_count_matches_sum_of_plugins():
    from molmcp_gateway.server import mcp
    from molmcp_lammps.server import mcp as lammps_mcp
    from molmcp_molexp.server import mcp as molexp_mcp
    from molmcp_molpy.server import mcp as molpy_mcp

    plugin_total = (
        len(asyncio.run(molpy_mcp.list_tools()))
        + len(asyncio.run(molexp_mcp.list_tools()))
        + len(asyncio.run(lammps_mcp.list_tools()))
    )
    gateway_total = len(asyncio.run(mcp.list_tools()))
    assert gateway_total == plugin_total, (
        f"gateway tool count {gateway_total} != sum of plugin counts {plugin_total}"
    )
