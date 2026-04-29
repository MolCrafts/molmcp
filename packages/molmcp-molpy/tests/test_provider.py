"""Tests for ``MolPyProvider``.

The provider is a structure-file inspector: it takes a file path,
dispatches to the appropriate ``molpy.io`` reader, and returns a
small summary dict. It does not write anything; tests use
``tmp_path`` fixtures to avoid touching the working tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("molmcp", reason="molcrafts-molmcp not installed")
pytest.importorskip("fastmcp", reason="fastmcp not installed")
pytest.importorskip("molpy", reason="molpy not installed")

from molmcp_molpy import MolPyProvider  # noqa: E402


def _build_server():
    from molmcp import create_server

    return create_server(
        name="molpy-test",
        providers=[MolPyProvider()],
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

    provider = MolPyProvider()
    assert isinstance(provider, Provider)
    assert provider.name == "molpy"


def test_two_tools_registered():
    server = _build_server()
    names = {t.name for t in _list_tools(server)}
    assert names == {"list_readers", "inspect_structure"}


def test_all_tools_have_read_only_annotation():
    server = _build_server()
    for tool in _list_tools(server):
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None
        assert getattr(annotations, "readOnlyHint", False) is True
        assert getattr(annotations, "openWorldHint", True) is False


def test_list_readers_returns_known_formats():
    server = _build_server()
    fn = _get_tool(server, "list_readers")
    out = fn()
    formats = {r["format"] for r in out["readers"]}
    assert {"lammps", "xyz", "pdb", "gro", "mol2"}.issubset(formats)
    for entry in out["readers"]:
        assert entry["kind"] == "structure"
        assert entry["extensions"], f"reader {entry['format']!r} missing extensions"


def test_inspect_structure_xyz_autodetect(tmp_path):
    path = _write_xyz(
        tmp_path / "water.xyz",
        [("H", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.0), ("O", 0.0, 0.0, 0.5)],
    )
    server = _build_server()
    fn = _get_tool(server, "inspect_structure")
    out = fn(str(path))
    assert out["format"] == "xyz"
    assert out["num_atoms"] == 3
    assert "atoms" in out["blocks"]


def test_inspect_structure_explicit_format(tmp_path):
    path = _write_xyz(
        tmp_path / "no_ext", [("C", 0.0, 0.0, 0.0)]
    )
    server = _build_server()
    fn = _get_tool(server, "inspect_structure")
    out = fn(str(path), format="xyz")
    assert out["format"] == "xyz"
    assert out["num_atoms"] == 1


def test_inspect_structure_missing_path(tmp_path):
    server = _build_server()
    fn = _get_tool(server, "inspect_structure")
    out = fn(str(tmp_path / "does_not_exist.xyz"))
    assert "error" in out
    assert "not found" in out["error"]


def test_inspect_structure_directory_path(tmp_path):
    server = _build_server()
    fn = _get_tool(server, "inspect_structure")
    out = fn(str(tmp_path))
    assert "error" in out
    assert "not a file" in out["error"]


def test_inspect_structure_unknown_extension(tmp_path):
    p = tmp_path / "structure.unknown"
    p.write_text("garbage")
    server = _build_server()
    fn = _get_tool(server, "inspect_structure")
    out = fn(str(p))
    assert "error" in out
    assert "auto-detect" in out["error"]
    assert "available_formats" in out


def test_inspect_structure_unknown_explicit_format(tmp_path):
    path = _write_xyz(tmp_path / "x.xyz", [("C", 0.0, 0.0, 0.0)])
    server = _build_server()
    fn = _get_tool(server, "inspect_structure")
    out = fn(str(path), format="not_a_format")
    assert "error" in out
    assert "unknown structure format" in out["error"]
