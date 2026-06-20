"""Tests for ``MolrsProvider``.

The provider is a read-only catalog + structure-file inspector. It
catalogs molrs's compute operators, neighbor algorithms, and I/O
functions (static tables aligned with the native ``molrs.molrs``
extension), and dispatches a single ``inspect_structure`` tool to the
matching ``molrs.read_*`` function. Tests use ``tmp_path`` fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastmcp", reason="fastmcp not installed")
pytest.importorskip("molrs", reason="molcrafts-molrs not installed")

from molmcp.providers.molrs import MolrsProvider  # noqa: E402


def _build_server():
    from molmcp import create_server

    return create_server(
        name="molrs-test",
        providers=[MolrsProvider()],
        discover_entry_points=False,
        discovery_sources=None,
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


def _molrs_has(name: str) -> bool:
    """True if ``name`` is exported by molrs (top-level or native module).

    The native compute classes (``RDF`` etc.) live on the ``molrs.molrs``
    extension module; the top-level package only re-exports the I/O
    functions and neighbor classes.
    """
    import molrs

    if hasattr(molrs, name):
        return True
    inner = getattr(molrs, "molrs", None)
    return inner is not None and hasattr(inner, name)


def _write_xyz(p: Path, atoms: list[tuple[str, float, float, float]]) -> Path:
    lines = [str(len(atoms)), "molrs provider test"]
    for el, x, y, z in atoms:
        lines.append(f"{el} {x} {y} {z}")
    p.write_text("\n".join(lines) + "\n")
    return p


# ── protocol ────────────────────────────────────────────────────────────


def test_provider_implements_molmcp_protocol():
    from molmcp import Provider

    provider = MolrsProvider()
    assert isinstance(provider, Provider)
    assert provider.name == "molrs"


def test_five_tools_registered():
    server = _build_server()
    names = {t.name for t in _list_tools(server)}
    assert names == {
        "list_compute_ops",
        "list_neighbor_algos",
        "list_readers",
        "list_writers",
        "inspect_structure",
    }


def test_all_tools_have_read_only_annotation():
    server = _build_server()
    for tool in _list_tools(server):
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None
        assert getattr(annotations, "readOnlyHint", False) is True
        assert getattr(annotations, "openWorldHint", True) is False


# ── catalog tools ───────────────────────────────────────────────────────


def test_list_compute_ops_covers_known_analyses():
    server = _build_server()
    fn = _get_tool(server, "list_compute_ops")
    out = fn()
    op_keys = {o["op"] for o in out["ops"]}
    # All canonical molrs analyses must appear.
    assert {
        "rdf",
        "msd",
        "cluster",
        "center_of_mass",
        "gyration_tensor",
        "inertia_tensor",
        "radius_of_gyration",
        "pca",
        "kmeans",
    }.issubset(op_keys)
    # Each entry must have the four required fields.
    for entry in out["ops"]:
        assert entry["class"]
        assert entry["signature"]
        assert entry["inputs"]
        assert entry["summary"]


def test_list_compute_ops_class_names_exist_on_molrs():
    """Every catalogued class name must actually be exported by molrs."""
    server = _build_server()
    out = _get_tool(server, "list_compute_ops")()
    for entry in out["ops"]:
        cls_name = entry["class"]
        assert _molrs_has(cls_name), (
            f"catalog references molrs.{cls_name} but molrs does not export it"
        )


def test_list_neighbor_algos_covers_canonical_set():
    server = _build_server()
    out = _get_tool(server, "list_neighbor_algos")()
    keys = {a["algo"] for a in out["algos"]}
    assert {"neighbor_query", "linked_cell", "neighbor_list"}.issubset(keys)


def test_list_neighbor_algos_class_names_exist_on_molrs():
    server = _build_server()
    out = _get_tool(server, "list_neighbor_algos")()
    for entry in out["algos"]:
        assert _molrs_has(entry["class"])


def test_list_readers_covers_canonical_set():
    server = _build_server()
    out = _get_tool(server, "list_readers")()
    keys = {r["format"] for r in out["readers"]}
    assert {"xyz", "pdb", "lammps"}.issubset(keys)


def test_list_readers_function_names_exist_on_molrs():
    server = _build_server()
    out = _get_tool(server, "list_readers")()
    for entry in out["readers"]:
        assert _molrs_has(entry["function"]), (
            f"catalog references molrs.{entry['function']} but it is not exported"
        )


def test_list_writers_function_names_exist_on_molrs():
    server = _build_server()
    out = _get_tool(server, "list_writers")()
    for entry in out["writers"]:
        assert _molrs_has(entry["function"])


# ── inspect_structure ───────────────────────────────────────────────────


def test_inspect_structure_xyz_autodetect(tmp_path):
    path = _write_xyz(
        tmp_path / "water.xyz",
        [("H", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.0), ("O", 0.0, 0.0, 0.5)],
    )
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(path))
    assert out.get("format") == "xyz", out
    assert out["num_atoms"] == 3


def test_inspect_structure_explicit_format(tmp_path):
    path = _write_xyz(tmp_path / "no_ext", [("C", 0.0, 0.0, 0.0)])
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(path), format="xyz")
    assert out.get("format") == "xyz", out
    assert out["num_atoms"] == 1


def test_inspect_structure_missing_path(tmp_path):
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(tmp_path / "nope.xyz"))
    assert "error" in out
    assert "not found" in out["error"]


def test_inspect_structure_directory_path(tmp_path):
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(tmp_path))
    assert "error" in out
    assert "not a file" in out["error"]


def test_inspect_structure_unknown_extension(tmp_path):
    p = tmp_path / "structure.unknown"
    p.write_text("garbage")
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(p))
    assert "error" in out
    assert "auto-detect" in out["error"]
    assert "available_formats" in out


def test_inspect_structure_unknown_explicit_format(tmp_path):
    path = _write_xyz(tmp_path / "x.xyz", [("C", 0.0, 0.0, 0.0)])
    server = _build_server()
    out = _get_tool(server, "inspect_structure")(str(path), format="not_a_format")
    assert "error" in out
    assert "unknown structure format" in out["error"]
