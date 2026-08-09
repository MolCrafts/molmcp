"""Small compatibility layer for optional Tree-sitter analyzers.

The analyzer package must remain importable without native parser wheels.  This
module therefore imports ``tree_sitter`` and the official language wheels only
when analysis is requested.  It intentionally has no language-pack fallback:
newer packs may download grammars on demand, which is inappropriate for a
local-first indexer.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Iterator

from ..schema import Edge, EdgeKind, Provenance, UnresolvedRef
from .base import AnalyzerNotAvailable

_GRAMMARS = {
    "rust": ("tree_sitter_rust", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
}


def get_parser(language: str) -> Any:
    """Return a parser configured from an official language wheel."""
    grammar = _GRAMMARS.get(language)
    if grammar is None:
        raise AnalyzerNotAvailable(f"unsupported Tree-sitter language: {language}")
    try:
        from tree_sitter import Language, Parser

        grammar_module = importlib.import_module(grammar[0])
    except (ImportError, OSError) as exc:
        raise AnalyzerNotAvailable(
            f"{language} analysis requires optional 'tree-sitter' and "
            f"'{grammar[0].replace('_', '-')}' packages"
        ) from exc

    try:
        raw_language = getattr(grammar_module, grammar[1])()
        try:
            configured_language = Language(raw_language)
        except TypeError:
            # Some older grammar wheels already return a Language instance.
            configured_language = raw_language

        try:
            return Parser(configured_language)
        except TypeError:
            # Compatibility with releases predating ``Parser(language)``.
            parser = Parser()
            try:
                parser.language = configured_language
            except AttributeError:
                parser.set_language(configured_language)
            return parser
    except Exception as exc:  # noqa: BLE001 - native backend errors vary by release
        raise AnalyzerNotAvailable(
            f"tree-sitter parser for {language!r} is unavailable: {exc}"
        ) from exc


def parse(language: str, source: str) -> tuple[Any, bytes]:
    """Parse UTF-8 source and return ``(root_node, encoded_source)``."""
    data = source.encode("utf-8")
    parser = get_parser(language)
    try:
        tree = parser.parse(data)
    except Exception as exc:  # noqa: BLE001 - isolate optional native bindings
        raise AnalyzerNotAvailable(
            f"tree-sitter parser for {language!r} failed: {exc}"
        ) from exc
    return tree.root_node, data


def node_text(node: Any, data: bytes) -> str:
    """Decode the byte span represented by a Tree-sitter node."""
    return data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def field(node: Any, name: str) -> Any | None:
    """Read a named field while tolerating binding/version differences."""
    try:
        return node.child_by_field_name(name)
    except (AttributeError, TypeError):
        return None


def named_children(node: Any) -> list[Any]:
    """Return named children from supported py-tree-sitter releases."""
    children = getattr(node, "named_children", None)
    if children is not None:
        return list(children)
    return [child for child in getattr(node, "children", ()) if child.is_named]


def descendants(node: Any) -> Iterator[Any]:
    """Yield all descendants in source order without using a stateful cursor."""
    stack = list(reversed(named_children(node)))
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(named_children(current)))


def start_line(node: Any) -> int:
    point = node.start_point
    row = point.row if hasattr(point, "row") else point[0]
    return int(row) + 1


def end_line(node: Any) -> int:
    point = node.end_point
    row = point.row if hasattr(point, "row") else point[0]
    return int(row) + 1


def compact(text: str) -> str:
    """Collapse a source fragment to a compact single-line signature."""
    return re.sub(r"\s+", " ", text).strip()


class TreeSitterBuilder:
    """Accumulate language-local graph facts with Tree-sitter provenance."""

    def __init__(self, file: str) -> None:
        self.file = file
        self.nodes: list[Any] = []
        self.edges: list[Edge] = []
        self.unresolved: list[UnresolvedRef] = []
        self._seen_refs: set[tuple[str, str, str]] = set()

    def contains(self, parent: str, child: str, line: int | None = None) -> None:
        self.edges.append(
            Edge(
                source=parent,
                target=child,
                kind=EdgeKind.CONTAINS,
                provenance=Provenance.TREE_SITTER,
                file=self.file,
                line=line,
            )
        )

    def ref(
        self, from_node: str, name: str, kind: str, line: int | None = None
    ) -> None:
        normalized = compact(name).strip(" ;")
        if not normalized:
            return
        key = (from_node, str(kind), normalized)
        if key in self._seen_refs:
            return
        self._seen_refs.add(key)
        self.unresolved.append(
            UnresolvedRef(
                from_node=from_node,
                name=normalized,
                kind=kind,
                file=self.file,
                line=line,
            )
        )
