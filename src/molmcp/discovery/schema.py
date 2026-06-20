"""Shared, language-agnostic graph representation.

Every language analyzer emits this schema and nothing else. The store,
resolver, query layer, and MCP tools all operate on these types, so the
graph stays uniform across Python, TypeScript, Rust, and C++.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

SCHEMA_VERSION = 3
# Bump when analyzer output changes — invalidates the extraction cache.
ANALYZER_VERSION = 1


class NodeKind(StrEnum):
    """Kinds of symbols a graph node can represent."""

    FILE = "file"
    PACKAGE = "package"
    MODULE = "module"
    NAMESPACE = "namespace"
    CLASS = "class"
    STRUCT = "struct"
    INTERFACE = "interface"
    TRAIT = "trait"
    ENUM = "enum"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    FIELD = "field"
    TYPE_ALIAS = "type_alias"
    CONSTANT = "constant"
    IMPORT = "import"
    EXPORT = "export"
    EXAMPLE = "example"
    TEST = "test"
    CAPABILITY = "capability"
    CONVENTION = "convention"


class EdgeKind(StrEnum):
    """Kinds of relationships a graph edge can represent."""

    CONTAINS = "contains"
    IMPORTS = "imports"
    EXPORTS = "exports"
    CALLS = "calls"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    REFERENCES = "references"
    RETURNS = "returns"
    INSTANTIATES = "instantiates"
    DECORATES = "decorates"
    OVERRIDES = "overrides"
    EXEMPLIFIES = "exemplifies"
    TESTS = "tests"
    PROVIDES_CAPABILITY = "provides_capability"
    GOVERNS = "governs"


class Provenance(StrEnum):
    """How an edge was established."""

    AST = "ast"
    HEURISTIC = "heuristic"
    RESOLVED = "resolved"


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


def node_id(file: str, qualname: str, kind: str) -> str:
    """Build a stable, within-snapshot-unique node id.

    Snapshots each have their own ``graph.db``, so ids only need to be
    unique within one snapshot — no snapshot prefix is required.
    """
    return f"{file}#{qualname}#{kind}"


@dataclass(slots=True)
class Node:
    """A symbol in the code graph."""

    id: str
    kind: str
    name: str
    qualname: str
    language: str
    file: str
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None
    summary: str | None = None
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    visibility: str = Visibility.PUBLIC
    is_exported: bool = False
    is_async: bool = False
    is_abstract: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": str(self.kind),
            "name": self.name,
            "qualname": self.qualname,
            "language": self.language,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "docstring": self.docstring,
            "summary": self.summary,
            "decorators": list(self.decorators),
            "bases": list(self.bases),
            "visibility": str(self.visibility),
            "is_exported": self.is_exported,
            "is_async": self.is_async,
            "is_abstract": self.is_abstract,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(
            id=d["id"],
            kind=d["kind"],
            name=d["name"],
            qualname=d["qualname"],
            language=d["language"],
            file=d["file"],
            start_line=d["start_line"],
            end_line=d["end_line"],
            signature=d.get("signature"),
            docstring=d.get("docstring"),
            summary=d.get("summary"),
            decorators=list(d.get("decorators", [])),
            bases=list(d.get("bases", [])),
            visibility=d.get("visibility", Visibility.PUBLIC),
            is_exported=d.get("is_exported", False),
            is_async=d.get("is_async", False),
            is_abstract=d.get("is_abstract", False),
            metadata=dict(d.get("metadata", {})),
        )


@dataclass(slots=True)
class Edge:
    """A relationship between two nodes."""

    source: str
    target: str
    kind: str
    provenance: str = Provenance.AST
    file: str | None = None
    line: int | None = None
    metadata: dict = field(default_factory=dict)
    id: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "kind": str(self.kind),
            "provenance": str(self.provenance),
            "file": self.file,
            "line": self.line,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(
            id=d.get("id"),
            source=d["source"],
            target=d["target"],
            kind=d["kind"],
            provenance=d.get("provenance", Provenance.AST),
            file=d.get("file"),
            line=d.get("line"),
            metadata=dict(d.get("metadata", {})),
        )


@dataclass(slots=True)
class UnresolvedRef:
    """A reference an analyzer could not resolve on its own.

    The Resolver (phase 2) turns these into :class:`Edge` objects when it
    can match ``name`` to a node within the snapshot; the rest are kept so
    dynamic references degrade gracefully instead of vanishing.
    """

    from_node: str
    name: str
    kind: str
    file: str | None = None
    line: int | None = None
    id: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_node": self.from_node,
            "name": self.name,
            "kind": str(self.kind),
            "file": self.file,
            "line": self.line,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UnresolvedRef":
        return cls(
            id=d.get("id"),
            from_node=d["from_node"],
            name=d["name"],
            kind=d["kind"],
            file=d.get("file"),
            line=d.get("line"),
        )


@dataclass(slots=True)
class FileRecord:
    """One source file that was walked and (attempted to be) analyzed."""

    path: str
    language: str
    content_hash: str
    size: int
    node_count: int = 0
    errors: list[str] = field(default_factory=list)
    indexed_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "language": self.language,
            "content_hash": self.content_hash,
            "size": self.size,
            "node_count": self.node_count,
            "errors": list(self.errors),
            "indexed_at": self.indexed_at,
        }


@dataclass(slots=True)
class CodeGraph:
    """The whole in-memory graph for one snapshot."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    files: list[FileRecord] = field(default_factory=list)
    unresolved: list[UnresolvedRef] = field(default_factory=list)

    def node_by_id(self, node_id: str) -> Node | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None
