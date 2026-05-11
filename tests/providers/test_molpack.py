"""Tests for ``MolpackProvider``.

The provider is a thin runtime-discovery layer over ``molpack``:
``list_restraints`` introspects the module for Restraint classes (no
hardcoded list), and ``inspect_script`` executes
:func:`molpack.load_script`. Tests use ``tmp_path`` fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastmcp", reason="fastmcp not installed")
pytest.importorskip("molpack", reason="molpack not installed")

from molmcp.providers.molpack import MolpackProvider  # noqa: E402


def _build_server():
    from molmcp import create_server

    return create_server(
        name="molpack-test",
        providers=[MolpackProvider()],
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
    lines = [str(len(atoms)), "molpack provider test"]
    for el, x, y, z in atoms:
        lines.append(f"{el} {x} {y} {z}")
    p.write_text("\n".join(lines) + "\n")
    return p


def _write_minimal_script(tmp_path: Path) -> tuple[Path, Path]:
    """Write a tiny .inp + structure pair, return (script, output_path)."""
    structure = _write_xyz(
        tmp_path / "water.xyz",
        [("H", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.0), ("O", 0.0, 0.0, 0.5)],
    )
    output = tmp_path / "packed.xyz"
    script = tmp_path / "mixture.inp"
    script.write_text(
        "tolerance 2.0\n"
        "seed 42\n"
        f"output {output.name}\n"
        "filetype xyz\n"
        "\n"
        f"structure {structure.name}\n"
        "  number 5\n"
        "  inside box 0.0 0.0 0.0 20.0 20.0 20.0\n"
        "end structure\n"
    )
    return script, output


def test_provider_implements_molmcp_protocol():
    from molmcp import Provider

    provider = MolpackProvider()
    assert isinstance(provider, Provider)
    assert provider.name == "molpack"


def test_three_tools_registered():
    server = _build_server()
    names = {t.name for t in _list_tools(server)}
    assert names == {"list_restraints", "list_formats", "inspect_script"}


def test_all_tools_have_read_only_annotation():
    server = _build_server()
    for tool in _list_tools(server):
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None
        assert getattr(annotations, "readOnlyHint", False) is True
        assert getattr(annotations, "openWorldHint", True) is False


def test_list_restraints_discovers_native_restraints():
    """Discovery must reach every native restraint molpack re-exports.

    The five built-in restraints are documented in ``molpack.__all__``;
    new ones added in future molpack releases will appear automatically
    via the ``*Restraint`` naming convention.
    """
    server = _build_server()
    out = _get_tool(server, "list_restraints")()
    discovered = {entry["name"] for entry in out["restraints"]}

    assert {
        "InsideBoxRestraint",
        "InsideSphereRestraint",
        "OutsideSphereRestraint",
        "AbovePlaneRestraint",
        "BelowPlaneRestraint",
    }.issubset(discovered)
    # The Protocol base itself must not appear in the catalog.
    assert "Restraint" not in discovered

    for entry in out["restraints"]:
        assert entry["signature"].startswith(entry["name"] + "(")
        assert set(entry) >= {"name", "signature", "summary"}


def test_list_formats_mirrors_rust_source():
    """Sanity-check the mirror against documented format strings.

    These five names must appear because the Rust ``read_frame`` match
    in ``molpack/src/script/io.rs`` has explicit arms for them. New
    formats added there should also be added to ``_SCRIPT_FORMATS``.
    """
    server = _build_server()
    out = _get_tool(server, "list_formats")()
    names = {entry["name"] for entry in out["formats"]}
    assert names == {"pdb", "xyz", "sdf", "lammps_dump", "lammps_data"}
    assert "molpack/src/script/io.rs" in out["source"]

    by_name = {entry["name"]: entry for entry in out["formats"]}
    # Aliases mirror the io.rs `|` patterns:
    assert "mol" in by_name["sdf"]["aliases"]
    assert "lammpstrj" in by_name["lammps_dump"]["aliases"]
    assert "data" in by_name["lammps_data"]["aliases"]
    # write_frame supports only pdb / xyz / lammpstrj
    assert by_name["pdb"]["write"] and by_name["xyz"]["write"]
    assert by_name["lammps_dump"]["write"]
    assert not by_name["sdf"]["write"]
    assert not by_name["lammps_data"]["write"]


def test_inspect_script_summarises_targets(tmp_path):
    script, output = _write_minimal_script(tmp_path)
    server = _build_server()
    fn = _get_tool(server, "inspect_script")
    out = fn(str(script))
    assert "error" not in out, out
    assert out["path"] == str(script)
    assert out["num_targets"] == 1
    assert out["targets"][0]["count"] == 5
    assert out["targets"][0]["natoms"] == 3
    assert out["num_atoms_total"] == 15
    assert Path(out["output"]).name == output.name


def test_inspect_script_missing_path(tmp_path):
    server = _build_server()
    fn = _get_tool(server, "inspect_script")
    out = fn(str(tmp_path / "does_not_exist.inp"))
    assert "error" in out
    assert "not found" in out["error"]


def test_inspect_script_directory_path(tmp_path):
    server = _build_server()
    fn = _get_tool(server, "inspect_script")
    out = fn(str(tmp_path))
    assert "error" in out
    assert "not a file" in out["error"]


def test_inspect_script_malformed(tmp_path):
    script = tmp_path / "broken.inp"
    script.write_text("this is not a valid packmol script\n")
    server = _build_server()
    fn = _get_tool(server, "inspect_script")
    out = fn(str(script))
    assert "error" in out
    assert "load_script failed" in out["error"]
