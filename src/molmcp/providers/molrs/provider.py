"""``molrs`` MCP provider — read-only catalog + structure-file inspector.

Scope is deliberately narrow: anything an agent could derive by reading
``molrs``'s source via :class:`molmcp.IntrospectionProvider` does **not**
belong here as static knowledge. ``molrs`` itself ships **no** MCP code;
this provider is the supported path for surfacing its compute / I-O
capabilities to agents.

Tools (all read-only):

* ``list_compute_ops`` — molrs trajectory-analysis operators
  (``RDF``, ``MSD``, ``Cluster``, ``CenterOfMass``, ``GyrationTensor``,
  ``InertiaTensor``, ``RadiusOfGyration``, ``Pca2``, ``KMeans``) with
  constructor signatures and one-line summaries. The catalog is the
  authoritative answer to "what analyses can molrs run?".
* ``list_neighbor_algos`` — the spatial-neighbor primitives
  (``NeighborQuery``, ``LinkedCell``, ``NeighborList``).
* ``list_readers`` — file readers exposed by ``molrs``.
* ``list_writers`` — file writers exposed by ``molrs``.
* ``inspect_structure`` — open a single-frame structure file via
  ``molrs`` and return a summary (format, block names, atom/bond
  counts, simbox info).

The provider never invokes a compute pipeline — RDF / MSD / Cluster /
PCA / KMeans return large arrays that should not flow through MCP.
Use the ``molrs`` Python API directly (``import molrs``) when you
actually want to compute.

Heavy ``molrs`` imports stay inside :meth:`register` and tool bodies so
the provider remains cheap to instantiate (e.g. for ``--print-config``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


# ── Compute-operator catalog ────────────────────────────────────────────
#
# Each entry maps a stable string key (the ``op`` argument the LLM may
# pass to follow-up tooling) to the molrs class name, the Python
# constructor signature, the upstream inputs, and a one-line summary.
#
# Keep this list aligned with what the native ``molrs.molrs`` extension
# actually exports.
_COMPUTE_OPS: dict[str, dict[str, object]] = {
    "rdf": {
        "class": "RDF",
        "signature": "RDF(n_bins, r_max, r_min=0.0)",
        "inputs": "frames: list[Frame], neighbors: list[NeighborList]",
        "summary": (
            "Radial distribution function g(r). Histograms pair "
            "distances from a per-frame neighbor list and normalises "
            "by ideal-gas shell volume; eagerly finalised."
        ),
    },
    "msd": {
        "class": "MSD",
        "signature": "MSD()",
        "inputs": "frames: list[Frame]",
        "summary": (
            "Mean squared displacement vs time. Uses frame 0 as the "
            "reference; returns per-time-lag MSD."
        ),
    },
    "cluster": {
        "class": "Cluster",
        "signature": "Cluster(min_cluster_size)",
        "inputs": "frames: list[Frame], neighbors: list[NeighborList]",
        "summary": (
            "Distance-based connected-component clustering on each "
            "frame's neighbor list. Returns one ClusterResult per frame."
        ),
    },
    "cluster_centers": {
        "class": "ClusterCenters",
        "signature": "ClusterCenters()",
        "inputs": "frames: list[Frame], clusters: list[ClusterResult]",
        "summary": "Centroid (centre of geometry) for each cluster, per frame.",
    },
    "center_of_mass": {
        "class": "CenterOfMass",
        "signature": "CenterOfMass(masses=None)",
        "inputs": "frames: list[Frame], clusters: list[ClusterResult]",
        "summary": (
            "Mass-weighted centre of mass per cluster, per frame. "
            "If ``masses`` is None, falls back to unit weights."
        ),
    },
    "gyration_tensor": {
        "class": "GyrationTensor",
        "signature": "GyrationTensor()",
        "inputs": (
            "frames: list[Frame], clusters: list[ClusterResult], "
            "centers: list[ClusterCentersResult]"
        ),
        "summary": (
            "3x3 gyration tensor per cluster, per frame. Pair with "
            "``RadiusOfGyration`` for the scalar Rg."
        ),
    },
    "inertia_tensor": {
        "class": "InertiaTensor",
        "signature": "InertiaTensor(masses=None)",
        "inputs": (
            "frames: list[Frame], clusters: list[ClusterResult], coms: list[COMResult]"
        ),
        "summary": (
            "3x3 inertia tensor per cluster, per frame, about the "
            "cluster's centre of mass."
        ),
    },
    "radius_of_gyration": {
        "class": "RadiusOfGyration",
        "signature": "RadiusOfGyration(masses=None)",
        "inputs": (
            "frames: list[Frame], clusters: list[ClusterResult], coms: list[COMResult]"
        ),
        "summary": "Scalar radius of gyration Rg per cluster, per frame.",
    },
    "pca": {
        "class": "Pca2",
        "signature": "Pca2()",
        "inputs": "rows: list[DescriptorRow]",
        "summary": (
            "Two-component PCA over a stack of per-cluster descriptor "
            "rows. Returns 2-D scores ready for ``KMeans``."
        ),
    },
    "kmeans": {
        "class": "KMeans",
        "signature": "KMeans(k, max_iter=100, seed=0)",
        "inputs": "pca_result: PcaResult",
        "summary": (
            "k-means clustering over a 2-D PCA projection. Seed is "
            "honoured for reproducibility."
        ),
    },
}


_NEIGHBOR_ALGOS: dict[str, dict[str, object]] = {
    "neighbor_query": {
        "class": "NeighborQuery",
        "signature": "NeighborQuery(box, points, cutoff)",
        "summary": (
            "freud-style spatial query. Build once over reference "
            "points; query repeatedly with ``query_self()`` or "
            "``query(query_points)``. Backed by a link-cell internally."
        ),
    },
    "linked_cell": {
        "class": "LinkedCell",
        "signature": "LinkedCell(box, points, cutoff)",
        "summary": (
            "Lower-level link-cell index. Prefer ``NeighborQuery`` "
            "unless you need direct cell access."
        ),
    },
    "neighbor_list": {
        "class": "NeighborList",
        "signature": "(returned by NeighborQuery.query / query_self)",
        "summary": (
            "Result type. Exposes ``n_pairs``, ``query_point_indices``, "
            "``point_indices``, ``distances``, ``dist_sq`` as borrowed "
            "numpy views into the Rust buffer."
        ),
    },
}


# ── File I/O catalog ────────────────────────────────────────────────────
#
# Each reader/writer key maps to the function name in the ``molrs``
# top-level namespace, the file extensions it handles, and a one-line
# summary. Used by ``inspect_structure`` to dispatch and by
# ``list_readers`` / ``list_writers`` to advertise capability.
_READERS: dict[str, dict[str, object]] = {
    "xyz": {
        "function": "read_xyz",
        "extensions": (".xyz",),
        "kind": "structure",
        "summary": "Plain XYZ coordinate file (single frame).",
    },
    "pdb": {
        "function": "read_pdb",
        "extensions": (".pdb",),
        "kind": "structure",
        "summary": "Protein Data Bank format.",
    },
    "lammps": {
        "function": "read_lammps",
        "extensions": (".data", ".lmp", ".lmps"),
        "kind": "structure",
        "summary": "LAMMPS data file.",
    },
    "lammps_traj": {
        "function": "read_lammps_traj",
        "extensions": (".lammpstrj", ".dump"),
        "kind": "trajectory",
        "summary": "LAMMPS dump trajectory.",
    },
    "xyz_traj": {
        "function": "read_xyz_trajectory",
        "extensions": (".xyz",),
        "kind": "trajectory",
        "summary": "Multi-frame XYZ trajectory.",
    },
    "chgcar": {
        "function": "read_chgcar_file",
        "extensions": (".chgcar",),
        "kind": "grid",
        "summary": "VASP CHGCAR charge-density grid.",
    },
    "cube": {
        "function": "read_cube_file",
        "extensions": (".cube",),
        "kind": "grid",
        "summary": "Gaussian cube file (volumetric).",
    },
    "smiles": {
        "function": "parse_smiles",
        "extensions": (),
        "kind": "smiles",
        "summary": "SMILES string parser; returns a SmilesIR.",
    },
}


_WRITERS: dict[str, dict[str, object]] = {
    "lammps": {
        "function": "write_lammps",
        "extensions": (".data", ".lmp", ".lmps"),
        "summary": "LAMMPS data file writer.",
    },
    "cube": {
        "function": "write_cube_file",
        "extensions": (".cube",),
        "summary": "Gaussian cube file writer (volumetric).",
    },
}


def _detect_reader(path: Path) -> str | None:
    """Return the reader key whose extensions cover ``path``, or ``None``.

    Prefers structure readers over trajectory/grid readers when the
    extension is shared (e.g. ``.xyz``).
    """
    ext = path.suffix.lower()
    # Two-pass: structure first (more specific), then anything.
    for kind in ("structure", "trajectory", "grid"):
        for key, info in _READERS.items():
            if info["kind"] == kind and ext in info["extensions"]:  # type: ignore[operator]
                return key
    return None


def _summarize_frame(frame: object, fmt: str, path: Path) -> dict:
    """Build a small JSON-serialisable summary of a molrs ``Frame``."""
    summary: dict[str, object] = {
        "path": str(path),
        "format": fmt,
    }
    try:
        summary["blocks"] = list(frame.keys())  # type: ignore[attr-defined]
    except Exception:
        summary["blocks"] = []

    for name in ("atoms", "bonds", "angles", "dihedrals", "impropers"):
        try:
            block = frame[name]  # type: ignore[index]
        except Exception:
            continue
        try:
            # molrs.Block.nrows is the row count (atom count etc.).
            # ``len(block)`` returns column count, not what we want.
            nrows = getattr(block, "nrows", None)
            if nrows is not None:
                summary[f"num_{name}"] = int(nrows)
        except Exception:
            pass

    try:
        sb = frame.simbox  # type: ignore[attr-defined]
    except Exception:
        sb = None
    if sb is not None:
        try:
            summary["simbox"] = {
                "volume": float(sb.volume()),
                "lengths": [float(x) for x in sb.lengths()],
                "pbc": [bool(x) for x in sb.pbc],
            }
        except Exception:
            pass

    try:
        meta = dict(frame.meta)  # type: ignore[attr-defined]
        if meta:
            summary["metadata"] = {k: str(v) for k, v in meta.items()}
    except Exception:
        pass

    return summary


class MolrsProvider:
    """Provider for molrs domain tools."""

    name = "molrs"

    def register(self, mcp: "FastMCP") -> None:
        try:
            import molrs  # noqa: F401 — eager probe; surface the missing dep
        except ImportError as exc:
            raise RuntimeError(
                "MolrsProvider requires the 'molcrafts-molrs' package. "
                "Install with: pip install molcrafts-molrs"
            ) from exc

        from mcp.types import ToolAnnotations

        ro = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

        @mcp.tool(annotations=ro)
        def list_compute_ops() -> dict:
            """List molrs's trajectory-analysis operator catalog.

            Returns:
                Dict with ``ops`` (each entry has ``op``, ``class``,
                ``signature``, ``inputs``, ``summary``) and a
                ``guidance`` string. For the full source of any op, use
                ``get_source`` / ``get_signature`` against the qualified
                name.
            """
            return {
                "ops": [
                    {
                        "op": key,
                        "class": info["class"],
                        "signature": info["signature"],
                        "inputs": info["inputs"],
                        "summary": info["summary"],
                    }
                    for key, info in _COMPUTE_OPS.items()
                ],
                "guidance": (
                    "Most ops take ``frames`` plus an upstream result "
                    "(NeighborList for RDF/Cluster, ClusterResult for "
                    "centre/tensor/Rg ops, DescriptorRow for PCA, "
                    "PcaResult for KMeans). Build the chain step-by-step "
                    "in Python; this MCP only catalogs."
                ),
            }

        @mcp.tool(annotations=ro)
        def list_neighbor_algos() -> dict:
            """List molrs's spatial-neighbor primitives.

            Returns:
                Dict with ``algos`` (each entry has ``algo``, ``class``,
                ``signature``, ``summary``) and ``guidance`` text.
            """
            return {
                "algos": [
                    {
                        "algo": key,
                        "class": info["class"],
                        "signature": info["signature"],
                        "summary": info["summary"],
                    }
                    for key, info in _NEIGHBOR_ALGOS.items()
                ],
                "guidance": (
                    "Default to ``NeighborQuery`` — it's the highest-level "
                    "API and what the compute ops consume. ``LinkedCell`` "
                    "is for advanced use; ``NeighborList`` is the result "
                    "type, not a constructor."
                ),
            }

        @mcp.tool(annotations=ro)
        def list_readers() -> dict:
            """List molrs file readers.

            Returns:
                Dict with ``readers`` (each entry has ``format``,
                ``function``, ``extensions``, ``kind``, ``summary``) and
                ``guidance``. Pass ``format=<key>`` to
                ``inspect_structure`` when extension auto-detection is
                ambiguous.
            """
            return {
                "readers": [
                    {
                        "format": key,
                        "function": info["function"],
                        "extensions": list(info["extensions"]),  # type: ignore[arg-type]
                        "kind": info["kind"],
                        "summary": info["summary"],
                    }
                    for key, info in _READERS.items()
                ],
                "guidance": (
                    "Pass ``format=<key>`` to ``inspect_structure`` "
                    "when extension auto-detection is ambiguous "
                    "(e.g. an .xyz trajectory vs single-frame .xyz)."
                ),
            }

        @mcp.tool(annotations=ro)
        def list_writers() -> dict:
            """List molrs file writers.

            Returns:
                Dict with ``writers`` (each entry has ``format``,
                ``function``, ``extensions``, ``summary``) and
                ``guidance``.
            """
            return {
                "writers": [
                    {
                        "format": key,
                        "function": info["function"],
                        "extensions": list(info["extensions"]),  # type: ignore[arg-type]
                        "summary": info["summary"],
                    }
                    for key, info in _WRITERS.items()
                ],
                "guidance": (
                    "Writers are exposed for catalog purposes only — "
                    "this MCP does not call them. Use ``import molrs`` "
                    "and the named function directly."
                ),
            }

        @mcp.tool(annotations=ro)
        def inspect_structure(path: str, format: str | None = None) -> dict:
            """Read a single-frame structure file via molrs and summarise it.

            Args:
                path: Filesystem path to the structure file. Subject to
                    the suite's path-safety policy.
                format: Optional explicit format key (e.g. ``"xyz"``,
                    ``"pdb"``, ``"lammps"``). When omitted, auto-detected
                    from the file extension. Call ``list_readers`` first
                    to discover what's available.

            Returns:
                Dict with ``path``, ``format``, ``blocks``, per-block
                counts (``num_atoms``, ``num_bonds``, …), ``simbox``
                (when present), and ``metadata``. Returns an ``error``
                key on failure (missing path, unknown format, reader
                exception).
            """
            p = Path(path)
            if not p.exists():
                return {"error": f"file not found: {path}", "path": str(p)}
            if not p.is_file():
                return {"error": f"not a file: {path}", "path": str(p)}

            fmt = format if format is not None else _detect_reader(p)
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

            import molrs

            reader_fn = getattr(molrs, _READERS[fmt]["function"])  # type: ignore[arg-type]
            try:
                frame = reader_fn(str(p))
            except Exception as exc:
                return {
                    "error": f"reader failed: {type(exc).__name__}: {exc}",
                    "format": fmt,
                    "path": str(p),
                }

            return _summarize_frame(frame, fmt, p)
