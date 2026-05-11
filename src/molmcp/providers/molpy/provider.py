"""``molpy`` MCP provider — runtime-discovered catalog + structure-file IO.

Scope is deliberately narrow: anything an agent could derive by reading
``molpy``'s source via :class:`molmcp.IntrospectionProvider` does **not**
belong here as static knowledge. This provider exists to (a) execute
``molpy.io`` readers on a path — something the introspection tools
cannot do — and (b) project a *filtered* view of the live module
(``Compute`` subclasses, ``DataReader`` subclasses) without
re-encoding their names, signatures, or summaries in this file.

Tools (all read-only):

* ``list_compute_ops`` — every ``molpy.compute.Compute`` subclass
  discovered at call-time, with constructor signature + docstring head.
* ``list_readers`` — every ``molpy.io.DataReader`` /
  ``BaseTrajectoryReader`` subclass discovered at call-time.
* ``inspect_structure`` — instantiate one of the discovered readers on
  a filesystem path and return a small ``Frame`` summary.

Heavy ``molpy`` imports stay inside :meth:`register` and tool bodies so
the provider remains cheap to instantiate (e.g. for ``--print-config``).
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
    params = list(sig.parameters.values())[1:]  # drop self
    rendered = ", ".join(str(p) for p in params)
    return f"{cls.__name__}({rendered})"


def _doc_head(obj: object) -> str:
    """First non-empty line of the cleaned docstring, or ''."""
    doc = inspect.getdoc(obj) or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _subclasses_in(module: object, base: type) -> list[type]:
    """Concrete ``base`` subclasses re-exported from ``module``.

    Ordered by class name for stable output. Excludes ``base`` itself
    and any abstract classes (those with non-empty ``__abstractmethods__``).
    """
    found: list[type] = []
    for name in dir(module):
        obj = getattr(module, name, None)
        if not inspect.isclass(obj) or obj is base:
            continue
        if not issubclass(obj, base):
            continue
        if getattr(obj, "__abstractmethods__", frozenset()):
            continue
        found.append(obj)
    found.sort(key=lambda c: c.__name__)
    return found


def _reader_entry(cls: type, kind: str) -> dict:
    return {
        "name": cls.__name__,
        "kind": kind,
        "signature": _signature(cls),
        "summary": _doc_head(cls),
    }


def _compute_entry(cls: type) -> dict:
    return {
        "name": cls.__name__,
        "signature": _signature(cls),
        "summary": _doc_head(cls),
    }


def _summarize_frame(frame: object, reader_name: str, path: Path) -> dict:
    """Build a small JSON-serialisable summary of a molpy ``Frame``."""
    block_names = list(getattr(frame, "_blocks", {}))
    summary: dict[str, object] = {
        "path": str(path),
        "reader": reader_name,
        "blocks": block_names,
    }
    for name in ("atoms", "bonds", "angles", "dihedrals", "impropers"):
        if name in block_names:
            try:
                summary[f"num_{name}"] = int(frame[name].nrows)  # type: ignore[index]
            except Exception:
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


class MolpyProvider:
    """Provider for molpy domain tools."""

    name = "molpy"

    def register(self, mcp: "FastMCP") -> None:
        try:
            import molpy  # noqa: F401 — eager probe; surface the missing dep
        except ImportError as exc:
            raise RuntimeError(
                "MolpyProvider requires the 'molcrafts-molpy' package. "
                "Install with: pip install molcrafts-molpy"
            ) from exc

        from mcp.types import ToolAnnotations

        ro = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

        @mcp.tool(annotations=ro)
        def list_compute_ops() -> dict:
            """List the ``Compute`` subclasses currently exposed by ``molpy.compute``.

            Returns:
                Dict with ``ops`` (each entry has ``name``, ``signature``,
                ``summary``) — discovered at call-time by walking
                ``molpy.compute`` for concrete ``Compute`` subclasses. For
                the full source of any op, use ``get_source`` /
                ``get_signature`` against the qualified name.
            """
            import molpy.compute as compute_mod

            return {
                "ops": [
                    _compute_entry(cls)
                    for cls in _subclasses_in(compute_mod, compute_mod.Compute)
                ],
            }

        @mcp.tool(annotations=ro)
        def list_readers() -> dict:
            """List the reader classes currently exposed by ``molpy.io``.

            Returns:
                Dict with ``readers`` (each entry has ``name``, ``kind`` =
                ``'structure'`` for ``DataReader`` subclasses or
                ``'trajectory'`` for ``BaseTrajectoryReader`` subclasses,
                ``signature``, ``summary``) — discovered at call-time. Pass
                ``name`` as the ``reader`` argument to ``inspect_structure``.
            """
            import molpy.io as io_mod

            structure = [
                _reader_entry(cls, "structure")
                for cls in _subclasses_in(io_mod, io_mod.DataReader)
            ]
            trajectory = [
                _reader_entry(cls, "trajectory")
                for cls in _subclasses_in(io_mod, io_mod.BaseTrajectoryReader)
            ]
            return {"readers": structure + trajectory}

        @mcp.tool(annotations=ro)
        def inspect_structure(path: str, reader: str) -> dict:
            """Read a single-frame structure file via a ``molpy.io`` reader.

            Args:
                path: Filesystem path to the structure file.
                reader: Class name of a ``DataReader`` subclass exposed
                    by ``molpy.io`` (e.g. ``"XYZReader"``,
                    ``"LammpsDataReader"``). Call ``list_readers`` first
                    to discover what's available.

            Returns:
                Dict with ``path``, ``reader``, ``blocks`` (block names
                molpy parsed), counts for the standard blocks
                (``num_atoms``, ``num_bonds``, …) when present, and any
                ``metadata`` molpy attached. Returns an ``error`` key on
                failure (missing path, unknown reader, reader exception).
            """
            p = Path(path)
            if not p.exists():
                return {"error": f"file not found: {path}", "path": str(p)}
            if not p.is_file():
                return {"error": f"not a file: {path}", "path": str(p)}

            import molpy.io as io_mod

            structure_readers = _subclasses_in(io_mod, io_mod.DataReader)
            by_name = {cls.__name__: cls for cls in structure_readers}
            cls = by_name.get(reader)
            if cls is None:
                return {
                    "error": f"unknown reader {reader!r}",
                    "path": str(p),
                    "available_readers": sorted(by_name),
                }

            try:
                instance = cls(p)
                frame = instance.read()
            except Exception as exc:
                return {
                    "error": f"reader failed: {type(exc).__name__}: {exc}",
                    "reader": reader,
                    "path": str(p),
                }

            return _summarize_frame(frame, reader, p)
