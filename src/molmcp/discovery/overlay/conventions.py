"""Domain-agnostic convention format and its graph contribution.

A ``[[convention]]`` table in the catalog TOML declares a scoped
coding/ecosystem convention:

    [[convention]]
    id = "style.molpy.core"
    scope = ["molpy.core"]
    title = "molpy.core write conventions"
    rules = ["Frame operations return new objects; never mutate"]
    tags = ["style", "immutability"]

Like capabilities, the *format* is core while the *content* ships with
a domain overlay package. Conventions become ``convention`` nodes
attached to their scope's package/module node via ``governs`` edges.
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
from . import CATALOG_FILE, OverlayContribution


@dataclass(slots=True)
class Convention:
    """One scoped convention from a catalog."""

    id: str
    scope: list[str]
    title: str = ""
    rules: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def load_conventions(path: str | Path) -> list[Convention]:
    """Parse ``[[convention]]`` tables from a catalog TOML file.

    Entries missing ``id`` or with a missing/empty ``scope`` are
    skipped (fail-soft, like :func:`.load_catalog`). A ``scope`` given
    as a single string is normalized to a one-element list.
    """
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    conventions: list[Convention] = []
    for entry in data.get("convention", []):
        if "id" not in entry or "scope" not in entry:
            continue
        raw_scope = entry["scope"]
        scope = (
            [str(raw_scope)]
            if isinstance(raw_scope, str)
            else [str(s) for s in raw_scope]
        )
        if not scope:
            continue
        conventions.append(
            Convention(
                id=str(entry["id"]),
                scope=scope,
                title=str(entry.get("title", "")),
                rules=[str(r) for r in entry.get("rules", [])],
                tags=[str(t) for t in entry.get("tags", [])],
            )
        )
    return conventions


_SCOPE_KINDS = {NodeKind.PACKAGE, NodeKind.MODULE, NodeKind.NAMESPACE}


def build_convention_contribution(
    conventions: list[Convention], graph: CodeGraph
) -> OverlayContribution:
    """Turn conventions into graph nodes/edges against a resolved graph.

    Each convention becomes a ``convention`` node; every scope entry is
    linked to its package/module/namespace node via a ``governs`` edge,
    or kept as an :class:`UnresolvedRef` when no node matches.
    """
    scope_nodes: dict[str, Node] = {}
    for node in graph.nodes:
        if node.kind in _SCOPE_KINDS:
            scope_nodes.setdefault(node.qualname, node)

    contribution = OverlayContribution()
    for convention in conventions:
        conv_id = node_id(CATALOG_FILE, convention.id, NodeKind.CONVENTION)
        contribution.nodes.append(
            Node(
                id=conv_id,
                kind=NodeKind.CONVENTION,
                name=convention.id,
                qualname=convention.id,
                language="convention",
                file=CATALOG_FILE,
                start_line=0,
                end_line=0,
                summary=convention.title,
                metadata={
                    "title": convention.title,
                    "scope": list(convention.scope),
                    "rules": list(convention.rules),
                    "tags": list(convention.tags),
                },
            )
        )
        for scope in convention.scope:
            target = scope_nodes.get(scope)
            if target is not None:
                contribution.edges.append(
                    Edge(
                        source=conv_id,
                        target=target.id,
                        kind=EdgeKind.GOVERNS,
                        provenance=Provenance.RESOLVED,
                    )
                )
            else:
                contribution.unresolved.append(
                    UnresolvedRef(
                        from_node=conv_id,
                        name=scope,
                        kind=EdgeKind.GOVERNS,
                    )
                )
    return contribution
