"""Domain capability overlays.

An overlay layers domain knowledge onto a snapshot's code graph *after*
resolution — without molmcp core ever importing the domain package. The
engine merges an overlay's :class:`OverlayContribution` (extra
``capability`` nodes and ``provides_capability`` edges) into the graph,
so every discovery tool works on capabilities for free.

Overlays are discovered via the ``molmcp.overlays`` entry-point group,
mirroring the ``molmcp.providers`` mechanism.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..schema import Edge, Node, UnresolvedRef

if TYPE_CHECKING:
    from ..schema import CodeGraph
    from ..source import Snapshot

logger = logging.getLogger(__name__)

OVERLAY_ENTRY_POINT_GROUP = "molmcp.overlays"

# Synthetic-file sentinel for overlay-born nodes. Feeds node_id(), so
# it is defined exactly once — a diverging redeclaration would silently
# split the overlay node-id namespace.
CATALOG_FILE = "<catalog>"


@dataclass(slots=True)
class OverlayContribution:
    """Extra graph elements an overlay merges in after resolution."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    unresolved: list[UnresolvedRef] = field(default_factory=list)


@runtime_checkable
class CapabilityOverlay(Protocol):
    """A domain overlay. Core never imports a domain package directly."""

    name: str

    def applies_to(self, snapshot: "Snapshot") -> bool:
        """Whether this overlay should contribute to ``snapshot``."""
        ...

    def contribute(self, graph: "CodeGraph") -> OverlayContribution:
        """Produce extra capability nodes/edges for a resolved graph."""
        ...


def load_overlays() -> list[CapabilityOverlay]:
    """Discover overlays declared via the ``molmcp.overlays`` entry points."""
    discovered: list[CapabilityOverlay] = []
    try:
        eps = importlib.metadata.entry_points(group=OVERLAY_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - very old importlib.metadata
        eps = importlib.metadata.entry_points().get(  # type: ignore[attr-defined]
            OVERLAY_ENTRY_POINT_GROUP, []
        )
    for ep in eps:
        try:
            instance = ep.load()()
        except Exception as exc:  # noqa: BLE001 - never let one overlay break load
            logger.warning("Failed to load overlay %r: %s", ep.name, exc)
            continue
        if not isinstance(instance, CapabilityOverlay):
            logger.warning("Entry point %r is not a CapabilityOverlay", ep.name)
            continue
        discovered.append(instance)
    return discovered
