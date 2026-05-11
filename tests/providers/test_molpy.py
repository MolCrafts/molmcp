"""Tests for ``MolpyProvider``.

The provider is a thin runtime-discovery layer over ``molpy``: catalog
tools introspect live module contents (no hardcoded class lists), and
``inspect_structure`` instantiates a discovered reader on a path.
Tests use ``tmp_path`` fixtures to avoid touching the working tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastmcp", reason="fastmcp not installed")
pytest.importorskip("molpy", reason="molpy not installed")

from molmcp.providers.molpy import MolpyProvider  # noqa: E402


def _build_server():
    from molmcp import create_server

    return create_server(
        name="molpy-test",
        providers=[MolpyProvider()],
        discover_entry_points=False,
        import_roots=None,
    )


def _list_tools(server):
    import asyncio

    return asyncio.run(server.list_tools())


def _get_tool(server, name: str):
    import asyncio

    tool = asyncio.run(server.get_tool(name))
    if tool is None:
        raise KeyError(f"tool {name!r} not registered")
    return tool.fn


def _write_xyz(p: Path, atoms: list[tuple[str, float, float, float]]) -> Path:
    lines = [str(len(atoms)), "molpy provider test"]
    for el, x, y, z in atoms:
        lines.append(f"{el} {x} {y} {z}")
    p.write_text("\n".join(lines) + "\n")
    return p


def test_provider_implements_molmcp_protocol():
    from molmcp import Provider

    provider = MolpyProvider()
    assert isinstance(provider, Provider)
    assert provider.name == "molpy"


def test_three_tools_registered():
    server = _build_server()
    names = {t.name for t in _list_tools(server)}
    assert names == {"list_readers", "list_compute_ops", "inspect_structure"}


def test_all_tools_have_read_only_annotation():
    server = _build_server()
    for tool in _list_tools(server):
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None
        assert getattr(annotations, "readOnlyHint", False) is True
        assert getattr(annotations, "openWorldHint", True) is False


def test_list_compute_ops_discovers_from_module():
    """Discovery must reach every concrete Compute subclass actually exported."""
    import inspect

    import molpy.compute as compute_mod

    expected = {
        name
        for name in dir(compute_mod)
        if inspect.isclass(getattr(compute_mod, name))
        and getattr(compute_mod, name) is not compute_mod.Compute
        and issubclass(getattr(compute_mod, name), compute_mod.Compute)
        and not getattr(
            getattr(compute_mod, name), "__abstractmethods__", frozenset()
        )
    }

    server = _build_server()
    out = _get_tool(server, "list_compute_ops")()
    discovered = {entry["name"] for entry in out["ops"]}
    assert discovered == expected
    for entry in out["ops"]:
        assert entry["signature"].startswith(entry["name"] + "(")
        # summary may be empty for undocumented classes
        assert set(entry) >= {"name", "signature", "summary"}


def test_list_readers_discovers_structure_and_trajectory():
    import inspect as _inspect

    import molpy.io as io_mod

    structure_expected = {
        name
        for name in dir(io_mod)
        if _inspect.isclass(getattr(io_mod, name))
        and getattr(io_mod, name) is not io_mod.DataReader
        and issubclass(getattr(io_mod, name), io_mod.DataReader)
        and not getattr(
            getattr(io_mod, name), "__abstractmethods__", frozenset()
        )
    }

    server = _build_server()
    out = _get_tool(server, "list_readers")()
    by_kind: dict[str, set[str]] = {}
    for entry in out["readers"]:
        by_kind.setdefault(entry["kind"], set()).add(entry["name"])
        assert entry["signature"].startswith(entry["name"] + "(")
        assert set(entry) >= {"name", "kind", "signature", "summary"}

    assert by_kind.get("structure") == structure_expected
    # Trajectory readers exist in molpy and must be tagged distinctly.
    assert "trajectory" in by_kind
    assert by_kind["structure"].isdisjoint(by_kind["trajectory"])


def test_inspect_structure_with_discovered_reader(tmp_path):
    path = _write_xyz(
        tmp_path / "water.xyz",
        [("H", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.0), ("O", 0.0, 0.0, 0.5)],
    )
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(path), reader="XYZReader")
    assert out["reader"] == "XYZReader"
    assert out["num_atoms"] == 3
    assert "atoms" in out["blocks"]


def test_inspect_structure_missing_path(tmp_path):
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(
        str(tmp_path / "does_not_exist.xyz"), reader="XYZReader"
    )
    assert "error" in out
    assert "not found" in out["error"]


def test_inspect_structure_directory_path(tmp_path):
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(tmp_path), reader="XYZReader")
    assert "error" in out
    assert "not a file" in out["error"]


def test_inspect_structure_unknown_reader(tmp_path):
    path = _write_xyz(tmp_path / "x.xyz", [("C", 0.0, 0.0, 0.0)])
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(path), reader="NotAReader")
    assert "error" in out
    assert "unknown reader" in out["error"]
    assert "available_readers" in out
    assert "XYZReader" in out["available_readers"]
