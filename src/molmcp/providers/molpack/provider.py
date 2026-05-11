"""``molpack`` MCP provider — runtime-discovered catalog + script execution.

Scope is deliberately narrow: anything an agent could derive by reading
``molpack``'s source via :class:`molmcp.IntrospectionProvider` does
**not** belong here as static knowledge. This provider exists to (a)
execute :func:`molpack.load_script` against a ``.inp`` script —
something the introspection tools cannot do, (b) project a *filtered*
view of the live module (``*Restraint`` classes) without re-encoding
their names, signatures, or summaries in this file, and (c) mirror
one piece of knowledge that lives only in molpack's **Rust** source
and has no Python-side registry to discover: the script-loader's
supported file formats.

Tools (all read-only):

* ``list_restraints`` — every restraint class discovered at call-time
  via the ``*Restraint`` name suffix in the live module.
* ``list_formats`` — static mirror of the input/output format table
  in ``molpack/src/script/io.rs``. The Rust source is the truth; this
  table is a typing shortcut for agents that needs hand-maintenance
  whenever Rust adds or renames a format.
* ``inspect_script`` — parse a Packmol-compatible ``.inp`` script via
  :func:`molpack.load_script` and return a summary (targets,
  per-target atom counts, output path, ``nloop``).

The provider never invokes :meth:`molpack.Molpack.pack` — packing is
compute-heavy and mutates files. Use the ``molpack`` CLI or Python API
directly when you actually want to run a pack.

Heavy ``molpack`` imports stay inside :meth:`register` and tool bodies
so the provider remains cheap to instantiate (e.g. for
``--print-config``).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _signature(cls: type) -> str:
    """Render ``cls.__init__`` signature with ``self`` stripped."""
    try:
        sig = inspect.signature(cls.__init__)
    except (ValueError, TypeError):
        return f"{cls.__name__}(...)"
    params = list(sig.parameters.values())[1:]
    rendered = ", ".join(str(p) for p in params)
    return f"{cls.__name__}({rendered})"


def _doc_head(obj: object) -> str:
    doc = inspect.getdoc(obj) or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


# Mirror of molpack/src/script/io.rs (read_frame + write_frame match arms,
# ext_format whitelist) as of molpack 0.1.0. Single source of truth lives in
# Rust; this table exists because molpack has no Python-side format registry.
# When io.rs gains or renames a format, update this list to match.
_SCRIPT_FORMATS: list[dict[str, object]] = [
    {
        "name": "pdb",
        "aliases": [],
        "extensions": [".pdb"],
        "read": True,
        "write": True,
    },
    {
        "name": "xyz",
        "aliases": [],
        "extensions": [".xyz"],
        "read": True,
        "write": True,
    },
    {
        "name": "sdf",
        "aliases": ["mol"],
        "extensions": [".sdf", ".mol"],
        "read": True,
        "write": False,
    },
    {
        "name": "lammps_dump",
        "aliases": ["lammpstrj"],
        "extensions": [".lammpstrj"],
        "read": True,
        "write": True,
    },
    {
        "name": "lammps_data",
        "aliases": ["data"],
        "extensions": [".data"],
        "read": True,
        "write": False,
    },
]


def _restraint_classes(module: object) -> list[type]:
    """Discover restraint classes re-exported from ``module``.

    molpack exposes a ``runtime_checkable`` ``Restraint`` Protocol that
    describes the duck-type contract for *user-defined* restraints
    (``f`` / ``fg`` methods). The built-in native pyo3 classes
    (``InsideBoxRestraint`` etc.) implement that contract in Rust and
    do **not** surface ``f`` / ``fg`` to Python — so
    ``issubclass(<native restraint>, Restraint)`` is ``False`` and the
    Protocol can't be used as the discovery base.

    Discovery therefore walks the naming convention molpack already
    uses in its ``__init__.py`` (everything ending in ``Restraint``
    except the Protocol base itself). Abstract classes are excluded.
    Ordered by class name.
    """
    found: list[type] = []
    for name in dir(module):
        if not name.endswith("Restraint") or name == "Restraint":
            continue
        obj = getattr(module, name, None)
        if not inspect.isclass(obj):
            continue
        if getattr(obj, "__abstractmethods__", frozenset()):
            continue
        found.append(obj)
    found.sort(key=lambda c: c.__name__)
    return found


def _restraint_entry(cls: type) -> dict:
    return {
        "name": cls.__name__,
        "signature": _signature(cls),
        "summary": _doc_head(cls),
    }


def _summarize_target(target: object, idx: int) -> dict:
    """Build a small JSON-serialisable summary of a molpack ``Target``."""
    summary: dict[str, object] = {"index": idx}
    for attr in ("name", "natoms", "count", "is_fixed"):
        try:
            summary[attr] = getattr(target, attr)
        except Exception:
            pass
    try:
        elements = list(target.elements)  # type: ignore[attr-defined]
        summary["element_counts"] = _element_counts(elements)
    except Exception:
        pass
    return summary


def _element_counts(elements: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for el in elements:
        counts[el] = counts.get(el, 0) + 1
    return counts


class MolpackProvider:
    """Provider for molpack domain tools."""

    name = "molpack"

    def register(self, mcp: "FastMCP") -> None:
        try:
            import molpack  # noqa: F401 — eager probe; surface the missing dep
        except ImportError as exc:
            raise RuntimeError(
                "MolpackProvider requires the 'molcrafts-molpack' package. "
                "Install with: pip install molcrafts-molpack"
            ) from exc

        from mcp.types import ToolAnnotations

        ro = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

        @mcp.tool(annotations=ro)
        def list_restraints() -> dict:
            """List the restraint classes currently exposed by ``molpack``.

            Returns:
                Dict with ``restraints`` (each entry has ``name``,
                ``signature``, ``summary``) — discovered at call-time
                by walking ``molpack`` for ``Restraint`` subclasses (or
                ``*Restraint``-named classes when no base is exposed).
                For full source of any restraint, use ``get_source`` /
                ``get_signature`` against the qualified name.
            """
            import molpack

            return {
                "restraints": [
                    _restraint_entry(cls) for cls in _restraint_classes(molpack)
                ],
            }

        @mcp.tool(annotations=ro)
        def list_formats() -> dict:
            """List the file formats molpack's script loader accepts.

            Returns:
                Dict with ``formats`` (each entry has ``name``,
                ``aliases`` — other filetype strings accepted as
                equivalents, ``extensions`` — used by molpack for
                auto-detection from the file extension, and ``read`` /
                ``write`` capability flags) and a ``source`` pointer at
                the Rust file this list mirrors.

                The Rust ``match`` arms in ``molpack/src/script/io.rs``
                are the source of truth — call ``read_file`` on that
                path via molmcp's introspection tools to verify.
            """
            return {
                "formats": [dict(entry) for entry in _SCRIPT_FORMATS],
                "source": "molpack/src/script/io.rs (read_frame, write_frame)",
            }

        @mcp.tool(annotations=ro)
        def inspect_script(path: str) -> dict:
            """Parse a Packmol-compatible ``.inp`` script and summarise it.

            Args:
                path: Filesystem path to the ``.inp`` script. Relative
                    paths inside the script are resolved by molpack
                    against the script's parent directory.

            Returns:
                Dict with ``path``, ``output`` (resolved output file),
                ``nloop`` (max outer iterations), ``num_targets``,
                ``num_atoms_total``, and ``targets`` (one entry per
                target with ``index``, ``name``, ``natoms``, ``count``,
                ``is_fixed``, ``element_counts``). Returns an ``error``
                key on failure.
            """
            p = Path(path)
            if not p.exists():
                return {"error": f"file not found: {path}", "path": str(p)}
            if not p.is_file():
                return {"error": f"not a file: {path}", "path": str(p)}

            from molpack import load_script

            try:
                job = load_script(str(p))
            except Exception as exc:
                return {
                    "error": f"load_script failed: {type(exc).__name__}: {exc}",
                    "path": str(p),
                }

            targets = list(job.targets)
            target_summaries = [_summarize_target(t, i) for i, t in enumerate(targets)]
            num_atoms_total = 0
            for s in target_summaries:
                natoms = s.get("natoms")
                count = s.get("count")
                if isinstance(natoms, int) and isinstance(count, int):
                    num_atoms_total += natoms * count
            return {
                "path": str(p),
                "output": job.output,
                "nloop": job.nloop,
                "num_targets": len(targets),
                "num_atoms_total": num_atoms_total,
                "targets": target_summaries,
            }
