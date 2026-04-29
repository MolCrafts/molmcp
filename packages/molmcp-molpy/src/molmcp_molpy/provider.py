"""``molpy`` MCP provider — read-only structure-file inspector.

The suite owns molpy's MCP integration. ``molpy`` itself ships **no**
MCP code; installing ``molcrafts-mcp-suite`` is the supported path.

Tools (all read-only):

* ``list_readers`` — enumerate the structure / trajectory readers
  ``molpy.io`` exposes, with file-extension hints.
* ``inspect_structure`` — open a single-frame structure file via
  ``molpy.io`` and return a summary (format, block names, atom/bond
  counts, metadata).

molpy's source code is *also* exposed by molmcp's source-introspection
tools (``read_file``, ``get_source``, ``list_modules``, …) when
``molpy`` is on the suite's ``import_roots``. The two surfaces are
complementary: introspection answers "how does this work?", these
tools answer "what's in this file?".

Heavy ``molpy`` imports stay inside :meth:`register` and tool bodies
so the provider remains cheap to instantiate — for example when the
CLI builds a server just to print the resolved configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


# Catalog of readers we surface. Each entry maps a stable string key
# (the ``format`` argument the LLM passes) to the reader class name in
# :mod:`molpy.io`, the file extensions we accept for auto-detection,
# the kind (``structure`` for single-frame, ``trajectory`` for
# multi-frame), and a one-line summary.
#
# Keep this list small and biased toward the formats users actually
# work with. Adding a new format is a single dict entry.
_READERS: dict[str, dict[str, object]] = {
    "lammps": {
        "reader": "LammpsDataReader",
        "extensions": (".data", ".lmps", ".lmp"),
        "kind": "structure",
        "summary": (
            "LAMMPS data file. Defaults to atom_style 'full'; "
            "pass an explicit reader_kwargs.atom_style if needed."
        ),
    },
    "xyz": {
        "reader": "XYZReader",
        "extensions": (".xyz",),
        "kind": "structure",
        "summary": "Plain XYZ coordinate file (single frame).",
    },
    "pdb": {
        "reader": "PDBReader",
        "extensions": (".pdb",),
        "kind": "structure",
        "summary": "Protein Data Bank format.",
    },
    "gro": {
        "reader": "GroReader",
        "extensions": (".gro",),
        "kind": "structure",
        "summary": "GROMACS coordinate file.",
    },
    "mol2": {
        "reader": "Mol2Reader",
        "extensions": (".mol2",),
        "kind": "structure",
        "summary": "SYBYL Mol2 format.",
    },
    "xsf": {
        "reader": "XsfReader",
        "extensions": (".xsf",),
        "kind": "structure",
        "summary": "XCrySDen Structure Format.",
    },
}


def _detect_format(path: Path) -> str | None:
    """Return the format key whose extensions cover ``path``, or ``None``."""
    ext = path.suffix.lower()
    for key, info in _READERS.items():
        if ext in info["extensions"]:  # type: ignore[operator]
            return key
    return None


def _summarize_frame(frame: object, fmt: str, path: Path) -> dict:
    """Build a small JSON-serialisable summary of a molpy ``Frame``."""
    block_names = list(getattr(frame, "_blocks", {}))
    summary: dict[str, object] = {
        "path": str(path),
        "format": fmt,
        "blocks": block_names,
    }
    for name in ("atoms", "bonds", "angles", "dihedrals", "impropers"):
        if name in block_names:
            try:
                summary[f"num_{name}"] = int(frame[name].nrows)  # type: ignore[index]
            except Exception:
                # Defensive: never let a flaky reader crash the tool.
                pass
    metadata = getattr(frame, "metadata", None)
    if metadata:
        try:
            summary["metadata"] = {
                k: str(v) for k, v in dict(metadata).items()
            }
        except Exception:
            pass
    return summary


class MolPyProvider:
    """Provider for molpy domain tools."""

    name = "molpy"

    def register(self, mcp: "FastMCP") -> None:
        from mcp.types import ToolAnnotations

        ro = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

        @mcp.tool(annotations=ro)
        def list_readers() -> dict:
            """List the molpy file-reader catalog.

            Returns:
                Dict with ``readers`` (each entry has ``format``,
                ``reader_class``, ``extensions``, ``kind``, ``summary``)
                and ``guidance`` text. Use ``format`` as the explicit
                argument to ``inspect_structure`` when the file
                extension is ambiguous.
            """
            return {
                "readers": [
                    {
                        "format": key,
                        "reader_class": info["reader"],
                        "extensions": list(info["extensions"]),  # type: ignore[arg-type]
                        "kind": info["kind"],
                        "summary": info["summary"],
                    }
                    for key, info in _READERS.items()
                ],
                "guidance": (
                    "Pass `format=<key>` to inspect_structure when "
                    "extension auto-detection is ambiguous (e.g. an .xyz "
                    "trajectory vs a single-frame .xyz)."
                ),
            }

        @mcp.tool(annotations=ro)
        def inspect_structure(
            path: str, format: str | None = None
        ) -> dict:
            """Read a single-frame structure file via molpy and summarise it.

            Args:
                path: Filesystem path to the structure file. Subject to
                    the suite's path-safety policy.
                format: Optional explicit format key (e.g. ``"lammps"``,
                    ``"xyz"``, ``"pdb"``). When omitted, auto-detected
                    from the file extension.

            Returns:
                Dict with ``path``, ``format``, ``blocks`` (block names
                molpy parsed), counts for the standard blocks
                (``num_atoms``, ``num_bonds``, …) when present, and
                any ``metadata`` molpy attached. Returns an ``error``
                key on failure.
            """
            p = Path(path)
            if not p.exists():
                return {"error": f"file not found: {path}", "path": str(p)}
            if not p.is_file():
                return {"error": f"not a file: {path}", "path": str(p)}

            fmt = format if format is not None else _detect_format(p)
            structure_keys = [
                k for k, v in _READERS.items() if v["kind"] == "structure"
            ]
            if fmt is None:
                return {
                    "error": (
                        f"could not auto-detect a structure format from "
                        f"extension {p.suffix!r}; pass an explicit format "
                        f"or use list_readers."
                    ),
                    "path": str(p),
                    "available_formats": structure_keys,
                }
            if fmt not in _READERS or _READERS[fmt]["kind"] != "structure":
                return {
                    "error": f"unknown structure format {fmt!r}",
                    "path": str(p),
                    "available_formats": structure_keys,
                }

            from molpy import io as molpy_io

            reader_cls = getattr(molpy_io, _READERS[fmt]["reader"])  # type: ignore[arg-type]
            try:
                reader = reader_cls(p)
                frame = reader.read()
            except Exception as exc:  # pragma: no cover — exercised via tests
                return {
                    "error": f"reader failed: {type(exc).__name__}: {exc}",
                    "format": fmt,
                    "path": str(p),
                }

            return _summarize_frame(frame, fmt, p)
