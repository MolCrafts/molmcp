"""C/C++ analyzer — registered stub.

Declares its extensions so the registry dispatches; real extraction
lands as an optional tree-sitter-backed extra.
"""

from __future__ import annotations

from ..schema import FileRecord
from .base import AnalyzerNotAvailable, AnalyzerResult


class CppAnalyzer:
    language = "cpp"
    extensions = frozenset({".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"})

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        raise AnalyzerNotAvailable(
            "C/C++ analysis needs the optional tree-sitter backend"
        )
