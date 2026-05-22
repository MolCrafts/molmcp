"""The multi-language seam: the analyzer contract.

A :class:`LanguageAnalyzer` turns one source file into raw graph nodes,
``contains`` edges, and :class:`UnresolvedRef` objects for everything
cross-file. Analyzers are language-local — they must NOT resolve
references across files; that is the Resolver's job (phase 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..schema import Edge, FileRecord, Node, UnresolvedRef


class AnalyzerNotAvailable(RuntimeError):
    """Raised by a stub analyzer whose backend is not implemented yet.

    The Extractor catches this, records the file with a note, and keeps
    going — so a repo with un-analyzable files still indexes cleanly.
    """


@dataclass(slots=True)
class AnalyzerResult:
    """What an analyzer produces for a single file."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    unresolved: list[UnresolvedRef] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class LanguageAnalyzer(Protocol):
    """Contract every language analyzer implements."""

    language: str
    extensions: frozenset[str]

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        """Extract a single file's symbols and references."""
        ...
