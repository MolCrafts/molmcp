"""TypeScript/JavaScript analyzer — registered stub.

Declares its extensions so the registry dispatches and the schema can
hold non-Python files, but defers real extraction. A tree-sitter-backed
implementation lands as an optional ``[treesitter]`` extra.
"""

from __future__ import annotations

from ..schema import FileRecord
from .base import AnalyzerNotAvailable, AnalyzerResult


class TypeScriptAnalyzer:
    language = "typescript"
    extensions = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs"})

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        raise AnalyzerNotAvailable(
            "TypeScript analysis needs the optional tree-sitter backend"
        )
