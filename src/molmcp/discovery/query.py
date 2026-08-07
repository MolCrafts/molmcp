"""DiscoveryQuery — the read API over a snapshot's graph.

Pure functions of a :class:`GraphStore`; no MCP, no I/O beyond SQLite.
This is what the MCP tools and the CLI both call.
"""

from __future__ import annotations

from .schema import Edge, EdgeKind, Node, NodeKind, Provenance
from .source import Snapshot
from .store import GraphStore

_KIND_ORDER: dict[str, int] = {
    NodeKind.PACKAGE: 0,
    NodeKind.MODULE: 1,
    NodeKind.NAMESPACE: 2,
    NodeKind.CAPABILITY: 2,
    NodeKind.CONVENTION: 2,
    NodeKind.CLASS: 3,
    NodeKind.STRUCT: 3,
    NodeKind.INTERFACE: 3,
    NodeKind.TRAIT: 3,
    NodeKind.ENUM: 3,
    NodeKind.FUNCTION: 4,
    NodeKind.METHOD: 4,
    NodeKind.TEST: 4,
    NodeKind.PROPERTY: 5,
    NodeKind.CONSTANT: 6,
    NodeKind.FIELD: 6,
    NodeKind.TYPE_ALIAS: 6,
    NodeKind.EXAMPLE: 9,
}

_MEMBER_KINDS = {
    NodeKind.METHOD,
    NodeKind.PROPERTY,
    NodeKind.FIELD,
    NodeKind.TEST,
    NodeKind.CLASS,
}
_TOPLEVEL_KINDS = {
    NodeKind.CLASS,
    NodeKind.STRUCT,
    NodeKind.INTERFACE,
    NodeKind.TRAIT,
    NodeKind.ENUM,
    NodeKind.FUNCTION,
    NodeKind.TEST,
    NodeKind.CONSTANT,
    NodeKind.CAPABILITY,
}


class DiscoveryQuery:
    """Structured queries over one indexed snapshot."""

    def __init__(
        self,
        store: GraphStore,
        snapshot: Snapshot | None = None,
        freshness: str = "fresh",
    ):
        self.store = store
        self.snapshot = snapshot
        self.freshness = freshness

    # -- lookup ------------------------------------------------------

    def search(
        self, query: str, kind: str | None = None, limit: int = 30
    ) -> list[Node]:
        return self.store.search(query, kind, limit)

    def get_node(self, qualname: str) -> Node | None:
        """Best node for a qualname (a qualname may map to several)."""
        candidates = self.store.nodes_by_qualname(qualname)
        if not candidates:
            return None
        return sorted(candidates, key=lambda n: (_KIND_ORDER.get(n.kind, 7), n.id))[0]

    def conventions_for(self, qualname: str, limit: int = 10) -> list[Node]:
        """Convention nodes whose scope prefix covers ``qualname``.

        Matching is dot-boundary-safe (scope ``a.b`` does not match
        ``a.b2.x``) and works at any symbol depth via the convention's
        metadata scopes — ``governs`` edges only attach at
        package/module granularity. Most specific scope first.
        """
        matches: list[tuple[int, Node]] = []
        for node in self.store.nodes_by_kind(NodeKind.CONVENTION):
            best = -1
            for scope in node.metadata.get("scope", []):
                if qualname == scope or qualname.startswith(scope + "."):
                    best = max(best, len(scope))
            if best >= 0:
                matches.append((best, node))
        matches.sort(key=lambda pair: (-pair[0], pair[1].qualname))
        return [node for _, node in matches[:limit]]

    # -- relationship walks ------------------------------------------

    def callers(self, qualname: str, limit: int = 40) -> list[Node]:
        return _nodes(self.callers_pairs(qualname, limit))

    def callers_pairs(self, qualname: str, limit: int = 40) -> list[tuple[Node, Edge]]:
        """Direct callers, each paired with its ``CALLS`` edge."""
        return self._incoming_pairs(qualname, EdgeKind.CALLS, limit)

    def caller_counts(self, node_ids: list[str]) -> dict[str, int]:
        """Batched RESOLVED incoming ``CALLS``-edge counts keyed by node id.

        Only resolved edges count: this is a relevance signal, and a guessed
        (heuristic) caller must never buy a symbol rank. Full caller lists
        for display go through :meth:`callers_pairs`, which keeps every edge.
        """
        return self.store.incoming_edge_counts(
            node_ids, EdgeKind.CALLS, provenance=Provenance.RESOLVED
        )

    def callees(self, qualname: str, limit: int = 40) -> list[Node]:
        return _nodes(self.callees_pairs(qualname, limit))

    def callees_pairs(self, qualname: str, limit: int = 40) -> list[tuple[Node, Edge]]:
        """Symbols this one calls, each paired with its ``CALLS`` edge."""
        return self._outgoing_pairs(qualname, EdgeKind.CALLS, limit)

    def implementers(self, qualname: str, limit: int = 40) -> list[Node]:
        return _nodes(self.implementers_pairs(qualname, limit))

    def implementers_pairs(
        self, qualname: str, limit: int = 40
    ) -> list[tuple[Node, Edge]]:
        """Subclasses/implementers, paired with the ``EXTENDS`` or
        ``IMPLEMENTS`` edge that links them."""
        node = self.get_node(qualname)
        if node is None:
            return []
        pairs = [
            (e.source, e)
            for e in self.store.edges_to(node.id, EdgeKind.EXTENDS)
            + self.store.edges_to(node.id, EdgeKind.IMPLEMENTS)
        ]
        return self._load_pairs(pairs, limit)

    # "subclasses" is the same walk under a friendlier name.
    subclasses = implementers
    subclasses_pairs = implementers_pairs

    def implementations(self, qualname: str, limit: int = 40) -> list[Node]:
        """Symbols that implement a ``capability`` node."""
        return _nodes(self.implementations_pairs(qualname, limit))

    def implementations_pairs(
        self, qualname: str, limit: int = 40
    ) -> list[tuple[Node, Edge]]:
        """Like :meth:`implementations`, paired with the
        ``PROVIDES_CAPABILITY`` edge."""
        return self._outgoing_pairs(qualname, EdgeKind.PROVIDES_CAPABILITY, limit)

    def references(self, qualname: str, limit: int = 40) -> list[Node]:
        return _nodes(self.references_pairs(qualname, limit))

    def references_pairs(
        self, qualname: str, limit: int = 40
    ) -> list[tuple[Node, Edge]]:
        """Any referrer (every edge kind except ``CONTAINS``), paired
        with the referencing edge."""
        node = self.get_node(qualname)
        if node is None:
            return []
        pairs = [
            (e.source, e)
            for e in self.store.edges_to(node.id)
            if e.kind != EdgeKind.CONTAINS
        ]
        return self._load_pairs(pairs, limit)

    def examples_of(self, qualname: str, limit: int = 20) -> list[Node]:
        return _nodes(self.examples_pairs(qualname, limit))

    def examples_pairs(self, qualname: str, limit: int = 20) -> list[tuple[Node, Edge]]:
        """Example snippets, paired with their ``EXEMPLIFIES`` edge."""
        return self._incoming_pairs(qualname, EdgeKind.EXEMPLIFIES, limit)

    def tests_of(self, qualname: str, limit: int = 20) -> list[Node]:
        return _nodes(self.tests_pairs(qualname, limit))

    def tests_pairs(self, qualname: str, limit: int = 20) -> list[tuple[Node, Edge]]:
        """Covering tests, paired with their ``TESTS`` edge."""
        return self._incoming_pairs(qualname, EdgeKind.TESTS, limit)

    def impact(self, qualname: str, depth: int = 2, limit: int = 60) -> list[Node]:
        """Transitive callers + subclasses up to ``depth`` hops."""
        return _nodes(self.impact_pairs(qualname, depth=depth, limit=limit))

    def impact_pairs(
        self, qualname: str, depth: int = 2, limit: int = 60
    ) -> list[tuple[Node, Edge]]:
        """Like :meth:`impact`, paired with the first-reaching edge."""
        node = self.get_node(qualname)
        if node is None:
            return []
        seen: set[str] = {node.id}
        frontier: list[str] = [node.id]
        collected: list[tuple[str, Edge]] = []
        for _ in range(max(depth, 1)):
            nxt: list[str] = []
            for nid in frontier:
                for edge in self.store.edges_to(
                    nid, EdgeKind.CALLS
                ) + self.store.edges_to(nid, EdgeKind.EXTENDS):
                    if edge.source not in seen:
                        seen.add(edge.source)
                        nxt.append(edge.source)
                        collected.append((edge.source, edge))
            frontier = nxt
            if not frontier:
                break
        return self._load_pairs(collected, limit)

    # -- structural --------------------------------------------------

    def package_card(self) -> dict:
        """The one summary line and module count a package listing needs.

        Two indexed reads on ``nodes.kind``. Building the whole module tree
        to pick a docstring out of it — which is what the packages page used
        to do — walks every module's children for an answer that is right
        here.
        """
        packages = self.store.nodes_by_kind(NodeKind.PACKAGE)
        modules = self.store.nodes_by_kind(NodeKind.MODULE)
        for candidates, origin in (
            (packages, "package_docstring"),
            (modules, "module_docstring"),
        ):
            for node in sorted(candidates, key=lambda n: (len(n.qualname), n.qualname)):
                if node.summary and node.summary.strip():
                    return {
                        "summary": node.summary.strip(),
                        "summary_source": origin,
                        "module_count": len(packages) + len(modules),
                    }
        return {
            "summary": None,
            "summary_source": "missing",
            "module_count": len(packages) + len(modules),
        }

    def outline(self, path: str | None = None) -> dict:
        """A packages/modules -> symbols -> members structural map."""
        modules = [
            n
            for n in self.store.nodes_by_kind(NodeKind.MODULE)
            + self.store.nodes_by_kind(NodeKind.PACKAGE)
            if _path_matches(n.file, path)
        ]
        modules.sort(key=lambda n: n.qualname)
        return {
            "modules": [self._module_outline(m) for m in modules],
            "module_count": len(modules),
        }

    def _module_outline(self, module: Node) -> dict:
        symbols = []
        for child in self._children(module.id):
            if child.kind not in _TOPLEVEL_KINDS:
                continue
            entry = _node_brief(child)
            if child.kind in {
                NodeKind.CLASS,
                NodeKind.STRUCT,
                NodeKind.INTERFACE,
                NodeKind.TRAIT,
                NodeKind.ENUM,
            }:
                entry["members"] = [
                    _node_brief(m)
                    for m in self._children(child.id)
                    if m.kind in _MEMBER_KINDS
                ]
            symbols.append(entry)
        symbols.sort(key=lambda s: s["start_line"])
        return {
            "qualname": module.qualname,
            "kind": str(module.kind),
            "file": module.file,
            "summary": module.summary,
            "symbols": symbols,
        }

    # -- internals ---------------------------------------------------

    def _children(self, node_id: str) -> list[Node]:
        ids = [e.target for e in self.store.edges_from(node_id, EdgeKind.CONTAINS)]
        return self._load(ids, limit=None)

    def _incoming_pairs(
        self, qualname: str, kind: str, limit: int
    ) -> list[tuple[Node, Edge]]:
        node = self.get_node(qualname)
        if node is None:
            return []
        pairs = [(e.source, e) for e in self.store.edges_to(node.id, kind)]
        return self._load_pairs(pairs, limit)

    def _outgoing_pairs(
        self, qualname: str, kind: str, limit: int
    ) -> list[tuple[Node, Edge]]:
        node = self.get_node(qualname)
        if node is None:
            return []
        pairs = [(e.target, e) for e in self.store.edges_from(node.id, kind)]
        return self._load_pairs(pairs, limit)

    def _load_pairs(
        self, pairs: list[tuple[str, Edge]], limit: int | None
    ) -> list[tuple[Node, Edge]]:
        found = self.store.get_nodes(node_id for node_id, _ in pairs)
        out: list[tuple[Node, Edge]] = []
        seen: set[str] = set()
        for node_id, edge in pairs:
            if node_id in seen:
                continue
            seen.add(node_id)
            node = found.get(node_id)
            if node is None:
                continue
            out.append((node, edge))
            if limit is not None and len(out) >= limit:
                break
        return out

    def _load(self, ids: list[str], limit: int | None) -> list[Node]:
        found = self.store.get_nodes(ids)
        out: list[Node] = []
        seen: set[str] = set()
        for node_id in ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            node = found.get(node_id)
            if node is None:
                continue
            out.append(node)
            if limit is not None and len(out) >= limit:
                break
        return out


def _nodes(pairs: list[tuple[Node, Edge]]) -> list[Node]:
    return [node for node, _ in pairs]


def _path_matches(file: str, path: str | None) -> bool:
    if path is None:
        return True
    return file == path or file.startswith(path.rstrip("/") + "/")


def _node_brief(node: Node) -> dict:
    return {
        "qualname": node.qualname,
        "name": node.name,
        "kind": str(node.kind),
        "start_line": node.start_line,
        "end_line": node.end_line,
        "summary": node.summary,
        "signature": node.signature,
    }
