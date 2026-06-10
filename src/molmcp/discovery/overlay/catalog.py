"""Domain-agnostic capability catalog format and a catalog-backed overlay.

A ``capability_catalog.toml`` declares curated capabilities:

    [[capability]]
    id = "compute.rdf"
    title = "Radial distribution function"
    summary = "Compute g(r) between atom selections."
    implemented_by = ["molpy.compute.rdf.RDF"]
    examples = ["examples/rdf_basic.py"]
    tags = ["analysis", "structure"]

The same file may also carry ``[[convention]]`` tables; see
:mod:`.conventions`. The *format* is core; the *content* ships with a
domain overlay package.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import (
    CodeGraph,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Provenance,
    UnresolvedRef,
    node_id,
)
from ..source import Snapshot
from . import OverlayContribution
from .conventions import (
    Convention,
    build_convention_contribution,
    load_conventions,
)

_CATALOG_FILE = "<catalog>"


@dataclass(slots=True)
class Capability:
    """One curated capability from a catalog."""

    id: str
    title: str = ""
    summary: str = ""
    implemented_by: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)


def load_catalog(path: str | Path) -> list[Capability]:
    """Parse a ``capability_catalog.toml`` file into Capability objects."""
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    capabilities: list[Capability] = []
    for entry in data.get("capability", []):
        if "id" not in entry:
            continue
        capabilities.append(
            Capability(
                id=str(entry["id"]),
                title=str(entry.get("title", "")),
                summary=str(entry.get("summary", "")),
                implemented_by=[str(x) for x in entry.get("implemented_by", [])],
                examples=[str(x) for x in entry.get("examples", [])],
                tags=[str(x) for x in entry.get("tags", [])],
                probes=[str(x) for x in entry.get("probes", [])],
            )
        )
    return capabilities


def build_contribution(
    capabilities: list[Capability], graph: CodeGraph
) -> OverlayContribution:
    """Turn capabilities into graph nodes/edges against a resolved graph."""
    by_qualname: dict[str, Node] = {}
    for node in graph.nodes:
        by_qualname.setdefault(node.qualname, node)

    contribution = OverlayContribution()
    for capability in capabilities:
        cap_id = node_id(_CATALOG_FILE, capability.id, NodeKind.CAPABILITY)
        contribution.nodes.append(
            Node(
                id=cap_id,
                kind=NodeKind.CAPABILITY,
                name=capability.id,
                qualname=capability.id,
                language="capability",
                file=_CATALOG_FILE,
                start_line=0,
                end_line=0,
                summary=capability.summary or capability.title,
                docstring=capability.title or None,
                metadata={"title": capability.title, "tags": capability.tags},
            )
        )
        for qualname in capability.implemented_by:
            target = by_qualname.get(qualname)
            if target is not None:
                contribution.edges.append(
                    Edge(
                        source=cap_id,
                        target=target.id,
                        kind=EdgeKind.PROVIDES_CAPABILITY,
                        provenance=Provenance.RESOLVED,
                    )
                )
            else:
                contribution.unresolved.append(
                    UnresolvedRef(
                        from_node=cap_id,
                        name=qualname,
                        kind=EdgeKind.PROVIDES_CAPABILITY,
                    )
                )
        for index, example_path in enumerate(capability.examples, 1):
            example_id = node_id(
                _CATALOG_FILE,
                f"{capability.id} (example {index})",
                NodeKind.EXAMPLE,
            )
            contribution.nodes.append(
                Node(
                    id=example_id,
                    kind=NodeKind.EXAMPLE,
                    name=f"{capability.id} example {index}",
                    qualname=f"{capability.id} (example {index})",
                    language="capability",
                    file=example_path,
                    start_line=0,
                    end_line=0,
                    summary=f"curated example for {capability.id}",
                    metadata={"source": "catalog", "path": example_path},
                )
            )
            contribution.edges.append(
                Edge(
                    source=example_id,
                    target=cap_id,
                    kind=EdgeKind.EXEMPLIFIES,
                    provenance=Provenance.HEURISTIC,
                )
            )
    return contribution


class CatalogOverlay:
    """A :class:`CapabilityOverlay` backed by a catalog TOML file."""

    def __init__(
        self,
        catalog_path: str | Path,
        name: str = "catalog",
        spec_contains: str | None = None,
    ) -> None:
        self.name = name
        self.catalog_path = Path(catalog_path)
        self.spec_contains = spec_contains
        self._capabilities: list[Capability] | None = None
        self._conventions: list[Convention] | None = None

    @property
    def capabilities(self) -> list[Capability]:
        if self._capabilities is None:
            self._capabilities = load_catalog(self.catalog_path)
        return self._capabilities

    @property
    def conventions(self) -> list[Convention]:
        """Conventions lazily parsed from the catalog file."""
        if self._conventions is None:
            self._conventions = load_conventions(self.catalog_path)
        return self._conventions

    def applies_to(self, snapshot: Snapshot) -> bool:
        if self.spec_contains is None:
            return True
        return self.spec_contains in snapshot.spec

    def contribute(self, graph: CodeGraph) -> OverlayContribution:
        """Merged capability + convention contribution for ``graph``."""
        contribution = build_contribution(self.capabilities, graph)
        extra = build_convention_contribution(self.conventions, graph)
        contribution.nodes.extend(extra.nodes)
        contribution.edges.extend(extra.edges)
        contribution.unresolved.extend(extra.unresolved)
        return contribution
