"""DiscoveryQuery — the read API over a snapshot's graph.

Pure functions of a :class:`GraphStore`; no MCP, no I/O beyond SQLite.
This is what the MCP tools and the CLI both call.
"""

from __future__ import annotations

from .schema import EdgeKind, Node, NodeKind
from .source import Snapshot
from .store import GraphStore

_KIND_ORDER: dict[str, int] = {
    NodeKind.PACKAGE: 0,
    NodeKind.MODULE: 1,
    NodeKind.NAMESPACE: 2,
    NodeKind.CAPABILITY: 2,
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
        return sorted(
            candidates, key=lambda n: (_KIND_ORDER.get(n.kind, 7), n.id)
        )[0]

    # -- relationship walks ------------------------------------------

    def callers(self, qualname: str, limit: int = 40) -> list[Node]:
        return self._incoming(qualname, EdgeKind.CALLS, limit)

    def callees(self, qualname: str, limit: int = 40) -> list[Node]:
        return self._outgoing(qualname, EdgeKind.CALLS, limit)

    def implementers(self, qualname: str, limit: int = 40) -> list[Node]:
        node = self.get_node(qualname)
        if node is None:
            return []
        ids = [
            e.source
            for e in self.store.edges_to(node.id, EdgeKind.EXTENDS)
            + self.store.edges_to(node.id, EdgeKind.IMPLEMENTS)
        ]
        return self._load(ids, limit)

    # "subclasses" is the same walk under a friendlier name.
    subclasses = implementers

    def implementations(self, qualname: str, limit: int = 40) -> list[Node]:
        """Symbols that implement a ``capability`` node."""
        return self._outgoing(qualname, EdgeKind.PROVIDES_CAPABILITY, limit)

    def references(self, qualname: str, limit: int = 40) -> list[Node]:
        node = self.get_node(qualname)
        if node is None:
            return []
        ids = [
            e.source
            for e in self.store.edges_to(node.id)
            if e.kind != EdgeKind.CONTAINS
        ]
        return self._load(ids, limit)

    def examples_of(self, qualname: str, limit: int = 20) -> list[Node]:
        return self._incoming(qualname, EdgeKind.EXEMPLIFIES, limit)

    def tests_of(self, qualname: str, limit: int = 20) -> list[Node]:
        return self._incoming(qualname, EdgeKind.TESTS, limit)

    def impact(
        self, qualname: str, depth: int = 2, limit: int = 60
    ) -> list[Node]:
        """Transitive callers + subclasses up to ``depth`` hops."""
        node = self.get_node(qualname)
        if node is None:
            return []
        seen: set[str] = {node.id}
        frontier: list[str] = [node.id]
        collected: list[str] = []
        for _ in range(max(depth, 1)):
            nxt: list[str] = []
            for nid in frontier:
                for edge in self.store.edges_to(
                    nid, EdgeKind.CALLS
                ) + self.store.edges_to(nid, EdgeKind.EXTENDS):
                    if edge.source not in seen:
                        seen.add(edge.source)
                        nxt.append(edge.source)
                        collected.append(edge.source)
            frontier = nxt
            if not frontier:
                break
        return self._load(collected, limit)

    # -- structural --------------------------------------------------

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
        ids = [
            e.target for e in self.store.edges_from(node_id, EdgeKind.CONTAINS)
        ]
        return self._load(ids, limit=None)

    def _incoming(self, qualname: str, kind: str, limit: int) -> list[Node]:
        node = self.get_node(qualname)
        if node is None:
            return []
        ids = [e.source for e in self.store.edges_to(node.id, kind)]
        return self._load(ids, limit)

    def _outgoing(self, qualname: str, kind: str, limit: int) -> list[Node]:
        node = self.get_node(qualname)
        if node is None:
            return []
        ids = [e.target for e in self.store.edges_from(node.id, kind)]
        return self._load(ids, limit)

    def _load(self, ids: list[str], limit: int | None) -> list[Node]:
        out: list[Node] = []
        seen: set[str] = set()
        for node_id in ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self.store.get_node(node_id)
            if node is None:
                continue
            out.append(node)
            if limit is not None and len(out) >= limit:
                break
        return out


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
