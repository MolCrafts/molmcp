"""Rust analyzer — registered stub.

Declares its extension so the registry dispatches; real extraction lands
as an optional tree-sitter-backed extra.
"""

from __future__ import annotations

from ..schema import FileRecord
from .base import AnalyzerNotAvailable, AnalyzerResult


class RustAnalyzer:
    language = "rust"
    extensions = frozenset({".rs"})

    def analyze(self, file: FileRecord, source: str) -> AnalyzerResult:
        raise AnalyzerNotAvailable(
            "Rust analysis needs the optional tree-sitter backend"
        )
