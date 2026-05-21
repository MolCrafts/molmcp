"""Resolution (phase 2): link names into a connected graph.

Turns the analyzer's :class:`UnresolvedRef` objects into resolved
:class:`Edge` objects where a target can be found within the snapshot,
links pytest tests to the symbols they exercise, and lifts code blocks
out of docstrings into first-class ``example`` nodes. References that
stay genuinely unresolvable (stdlib calls, dynamic imports) are kept in
``graph.unresolved`` so they degrade gracefully.
"""

from __future__ import annotations

from .schema import (
    CodeGraph,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    Provenance,
    UnresolvedRef,
    node_id,
)

_CALLABLE_KINDS = {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.TEST}
_TYPE_KINDS = {
    NodeKind.CLASS,
    NodeKind.STRUCT,
    NodeKind.INTERFACE,
    NodeKind.TRAIT,
    NodeKind.ENUM,
}
_MODULE_KINDS = {NodeKind.MODULE, NodeKind.PACKAGE, NodeKind.NAMESPACE}


class Resolver:
    """Phase-2 resolver. Mutates and returns the graph it is given."""

    def __init__(self) -> None:
        self._by_qualname: dict[str, list[Node]] = {}
        self._by_name: dict[str, list[Node]] = {}
        self._by_id: dict[str, Node] = {}

    def resolve(self, graph: CodeGraph) -> CodeGraph:
        self._index_nodes(graph.nodes)
        self._resolve_refs(graph)
        self._link_tests(graph)
        self._extract_examples(graph)
        return graph

    # -- indexing ----------------------------------------------------

    def _index_nodes(self, nodes: list[Node]) -> None:
        self._by_qualname.clear()
        self._by_name.clear()
        self._by_id.clear()
        for node in nodes:
            self._by_qualname.setdefault(node.qualname, []).append(node)
            self._by_name.setdefault(node.name, []).append(node)
            self._by_id[node.id] = node

    def _pick(
        self,
        candidates: list[Node],
        ref_file: str | None,
        kinds: set[str] | None,
    ) -> Node | None:
        pool = [c for c in candidates if kinds is None or c.kind in kinds]
        if not pool:
            return None
        if ref_file is not None:
            same_file = [c for c in pool if c.file == ref_file]
            if same_file:
                pool = same_file
        return sorted(pool, key=lambda n: n.id)[0]

    # -- reference resolution ----------------------------------------

    def _resolve_refs(self, graph: CodeGraph) -> None:
        still_unresolved: list[UnresolvedRef] = []
        seen: set[tuple[str, str, str]] = set()
        for ref in graph.unresolved:
            edge = self._resolve_ref(ref)
            if edge is None:
                still_unresolved.append(ref)
                continue
            key = (edge.source, edge.target, str(edge.kind))
            if key in seen:
                continue
            seen.add(key)
            graph.edges.append(edge)
        graph.unresolved = still_unresolved

    def _resolve_ref(self, ref: UnresolvedRef) -> Edge | None:
        if ref.kind == EdgeKind.CALLS:
            return self._resolve_call(ref)
        if ref.kind == EdgeKind.EXTENDS:
            return self._resolve_type(ref)
        if ref.kind == EdgeKind.IMPORTS:
            return self._resolve_import(ref)
        return None

    def _edge(self, ref: UnresolvedRef, target: Node, prov: str) -> Edge:
        return Edge(
            source=ref.from_node,
            target=target.id,
            kind=ref.kind,
            provenance=prov,
            file=ref.file,
            line=ref.line,
        )

    def _resolve_call(self, ref: UnresolvedRef) -> Edge | None:
        simple = ref.name.split(".")[-1]
        if simple in ("", "self", "cls", "super"):
            return None
        target = self._pick(
            self._by_name.get(simple, []), ref.file, _CALLABLE_KINDS
        )
        if target is None or target.id == ref.from_node:
            return None
        return self._edge(ref, target, Provenance.HEURISTIC)

    def _resolve_type(self, ref: UnresolvedRef) -> Edge | None:
        exact = self._pick(
            self._by_qualname.get(ref.name, []), ref.file, _TYPE_KINDS
        )
        if exact is not None:
            return self._edge(ref, exact, Provenance.RESOLVED)
        simple = ref.name.split(".")[-1]
        target = self._pick(
            self._by_name.get(simple, []), ref.file, _TYPE_KINDS
        )
        if target is None:
            return None
        return self._edge(ref, target, Provenance.HEURISTIC)

    def _resolve_import(self, ref: UnresolvedRef) -> Edge | None:
        abs_name = self._absolute_import_name(ref)
        if not abs_name:
            return None
        target = self._pick(
            self._by_qualname.get(abs_name, []), ref.file, None
        )
        if target is None:
            return None
        return self._edge(ref, target, Provenance.RESOLVED)

    def _absolute_import_name(self, ref: UnresolvedRef) -> str:
        """Turn a (possibly relative) import name into a snapshot qualname."""
        name = ref.name
        if not name.startswith("."):
            return name
        importer = self._by_id.get(ref.from_node)
        if importer is None:
            return ""
        level = len(name) - len(name.lstrip("."))
        rest = name.lstrip(".")
        if importer.kind == NodeKind.PACKAGE:
            base_parts = importer.qualname.split(".")
        else:
            base_parts = importer.qualname.split(".")[:-1]
        drop = level - 1
        if drop > 0:
            base_parts = base_parts[:-drop] if drop <= len(base_parts) else []
        parts = [p for p in base_parts if p]
        if rest:
            parts.append(rest)
        return ".".join(parts)

    # -- test linking ------------------------------------------------

    def _link_tests(self, graph: CodeGraph) -> None:
        seen: set[tuple[str, str]] = set()
        for node in list(graph.nodes):
            if node.kind != NodeKind.TEST:
                continue
            subject = node.name[len("test_"):]
            if not subject:
                continue
            target = self._pick(
                self._by_name.get(subject, []),
                node.file,
                _CALLABLE_KINDS | _TYPE_KINDS,
            )
            if target is None or target.id == node.id:
                continue
            key = (node.id, target.id)
            if key in seen:
                continue
            seen.add(key)
            graph.edges.append(
                Edge(
                    source=node.id,
                    target=target.id,
                    kind=EdgeKind.TESTS,
                    provenance=Provenance.HEURISTIC,
                    file=node.file,
                )
            )

    # -- example extraction ------------------------------------------

    def _extract_examples(self, graph: CodeGraph) -> None:
        new_nodes: list[Node] = []
        new_edges: list[Edge] = []
        for node in graph.nodes:
            if not node.docstring or node.kind == NodeKind.EXAMPLE:
                continue
            for index, code in enumerate(_code_blocks(node.docstring), 1):
                ex_qual = f"{node.qualname} (example {index})"
                ex_id = node_id(node.file, ex_qual, NodeKind.EXAMPLE)
                new_nodes.append(
                    Node(
                        id=ex_id,
                        kind=NodeKind.EXAMPLE,
                        name=f"{node.name} example {index}",
                        qualname=ex_qual,
                        language=node.language,
                        file=node.file,
                        start_line=node.start_line,
                        end_line=node.end_line,
                        summary=f"usage example for {node.qualname}",
                        metadata={"code": code, "source": "docstring"},
                    )
                )
                new_edges.append(
                    Edge(
                        source=ex_id,
                        target=node.id,
                        kind=EdgeKind.EXEMPLIFIES,
                        provenance=Provenance.HEURISTIC,
                        file=node.file,
                    )
                )
        graph.nodes.extend(new_nodes)
        graph.edges.extend(new_edges)


def _code_blocks(docstring: str) -> list[str]:
    """Extract fenced and doctest code blocks from a docstring."""
    blocks: list[str] = []
    lines = docstring.splitlines()

    fence: list[str] | None = None
    doctest: list[str] = []

    def flush_doctest() -> None:
        if doctest:
            blocks.append("\n".join(doctest).strip())
            doctest.clear()

    for line in lines:
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith("```"):
                blocks.append("\n".join(fence).strip())
                fence = None
            else:
                fence.append(line)
            continue
        if stripped.startswith("```"):
            flush_doctest()
            fence = []
            continue
        if stripped.startswith(">>>") or (doctest and stripped.startswith("...")):
            doctest.append(stripped)
        else:
            flush_doctest()
    flush_doctest()
    return [b for b in blocks if b]
