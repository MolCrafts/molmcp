"""Source-code introspection Provider — the only built-in Provider."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .modules import list_modules_under, list_symbols_in
from .search import search_in_sources
from .source import (
    get_docstring_of,
    get_signature_of,
    get_source_of,
    read_package_file,
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


class IntrospectionProvider:
    """Provider that exposes 7 read-only source-code tools.

    Tools are bound to a configured set of *import roots* — top-level
    package names whose source the tools may read. Set ``import_roots=[]``
    to disable; the provider then registers nothing.
    """

    name = "introspection"

    def __init__(self, import_roots: list[str]):
        self.import_roots = list(import_roots)

    def register(self, mcp: FastMCP) -> None:
        if not self.import_roots:
            return

        roots = self.import_roots

        @mcp.tool(annotations=_READ_ONLY)
        def list_modules(prefix: str | None = None) -> list[str]:
            """List importable modules under the configured import roots.

            Args:
                prefix: Optional dotted-path prefix filter.

            Returns:
                Sorted list of fully-qualified module names.
            """
            return list_modules_under(roots, prefix)

        @mcp.tool(annotations=_READ_ONLY)
        def list_symbols(symbol: str) -> dict[str, str]:
            """List public symbols of a module **or** members of a class.

            For a module: returns ``{name: one_line_summary}``.

            For a class: returns ``{name: "<kind> — summary"}`` where
            ``kind`` is ``method`` / ``classmethod`` / ``staticmethod`` /
            ``property`` / ``attribute`` / ``nested_class``.  This is
            how to discover instance methods on a Python class without
            pulling its full source.

            Args:
                symbol: Fully-qualified dotted name.  Examples:
                    ``molpy.core.atomistic`` (module) or
                    ``molpy.core.atomistic.Atomistic`` (class).
            """
            return list_symbols_in(symbol)

        @mcp.tool(annotations=_READ_ONLY)
        def get_source(symbol: str) -> str:
            """Return the source code of a module, class, or function.

            Args:
                symbol: Fully-qualified dotted name. Examples:
                    ``molpy.core.atomistic``,
                    ``molpy.core.atomistic.Atomistic``,
                    ``molpy.reacter.Reacter.run``.
            """
            return get_source_of(symbol)

        @mcp.tool(annotations=_READ_ONLY)
        def get_docstring(symbol: str) -> str:
            """Return the cleaned docstring of a module, class, or function."""
            return get_docstring_of(symbol)

        @mcp.tool(annotations=_READ_ONLY)
        def get_signature(symbol: str) -> str:
            """Return the call signature of a callable."""
            return get_signature_of(symbol)

        @mcp.tool(annotations=_READ_ONLY)
        def read_file(
            relative_path: str, start: int = 1, end: int | None = None
        ) -> str:
            """Read a line range from a source file inside an import root.

            Args:
                relative_path: Path relative to the package parent directory,
                    e.g. ``molpy/core/atomistic.py``. ``..`` is rejected.
                start: 1-based start line (inclusive). Default 1.
                end: 1-based end line (inclusive). Default: end of file.
            """
            return read_package_file(roots, relative_path, start, end)

        @mcp.tool(annotations=_READ_ONLY)
        def search_source(
            query: str,
            module_prefix: str | None = None,
            max_results: int = 50,
        ) -> list[dict[str, str]]:
            """Case-insensitive substring search across package source files.

            Args:
                query: Text to find.
                module_prefix: Optional dotted-path filter.
                max_results: Maximum hits returned (capped at 50).

            Returns:
                List of ``{file, line, text}`` dicts.
            """
            return search_in_sources(roots, query, module_prefix, min(max_results, 50))


__all__ = ["IntrospectionProvider"]
