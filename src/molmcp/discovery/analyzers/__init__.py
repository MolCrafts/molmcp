"""Analyzer registry — dispatches files to language analyzers by extension."""

from __future__ import annotations

import os

from .base import AnalyzerNotAvailable, AnalyzerResult, LanguageAnalyzer
from .config import JsonAnalyzer, TomlAnalyzer
from .cpp import CppAnalyzer
from .markdown import MarkdownAnalyzer
from .python import PythonAnalyzer
from .rust import RustAnalyzer
from .typescript import TypeScriptAnalyzer

_ANALYZERS: list[LanguageAnalyzer] = [
    PythonAnalyzer(),
    TypeScriptAnalyzer(),
    RustAnalyzer(),
    MarkdownAnalyzer(),
    JsonAnalyzer(),
    TomlAnalyzer(),
    CppAnalyzer(),
]

# Extension (lowercased, with dot) -> analyzer.
ANALYZER_REGISTRY: dict[str, LanguageAnalyzer] = {
    ext: analyzer for analyzer in _ANALYZERS for ext in analyzer.extensions
}


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def get_analyzer_for(path: str) -> LanguageAnalyzer | None:
    """Return the analyzer for ``path``'s extension, or None."""
    return ANALYZER_REGISTRY.get(_ext(path))


def language_for_path(path: str) -> str | None:
    """Return the language id for ``path``, or None if unrecognized."""
    analyzer = get_analyzer_for(path)
    return analyzer.language if analyzer else None


__all__ = [
    "ANALYZER_REGISTRY",
    "AnalyzerNotAvailable",
    "AnalyzerResult",
    "LanguageAnalyzer",
    "get_analyzer_for",
    "language_for_path",
]
