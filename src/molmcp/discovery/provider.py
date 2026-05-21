"""DiscoveryProvider — the FastMCP interface to the discovery engine.

This is the only module in :mod:`molmcp.discovery` that imports MCP
machinery. It is a thin shell: every tool resolves a configured source,
runs a :class:`DiscoveryQuery`, and returns a plain dict carrying a
``snapshot`` freshness block.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from mcp.types import ToolAnnotations

from .config import DiscoveryConfig
from .engine import DiscoveryEngine
from .evidence import EvidenceBuilder, example_view, node_brief
from .query import DiscoveryQuery
from .source import Snapshot, SourceError

if TYPE_CHECKING:
    from fastmcp import FastMCP

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

_RELATIONS = (
    "callers",
    "callees",
    "implementers",
    "subclasses",
    "references",
    "examples",
    "tests",
    "impact",
)
_MAX_OUTLINE_MODULES = 300


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def _snapshot_block(snapshot: Snapshot) -> dict:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "origin": snapshot.origin,
        "spec": snapshot.spec,
        "commit": snapshot.commit,
        "file_count": snapshot.file_count,
        "freshness": "fresh",
    }


class DiscoveryProvider:
    """Registers the ``molmcp_*`` graph-discovery tools on a server."""

    name = "discovery"

    def __init__(
        self,
        sources: list[str] | None = None,
        config: DiscoveryConfig | None = None,
    ) -> None:
        self.sources = list(sources or [])
        self._config = config
        self._engine: DiscoveryEngine | None = None

    def engine(self) -> DiscoveryEngine:
        if self._engine is None:
            self._engine = DiscoveryEngine(self._config or DiscoveryConfig())
        return self._engine

    # -- source selection --------------------------------------------

    def _select_source(self, source: str | None) -> tuple[str | None, dict | None]:
        if not self.sources:
            return None, {"error": "no discovery sources are configured"}
        if source is None:
            return self.sources[0], None
        if source in self.sources:
            return source, None
        return None, {
            "error": f"unknown source {source!r}",
            "available_sources": list(self.sources),
        }

    def _with_query(
        self, source: str | None, build: Callable[[DiscoveryQuery], dict]
    ) -> dict:
        spec, err = self._select_source(source)
        if err is not None:
            return err
        try:
            query = self.engine().query(spec)
        except SourceError as exc:
            return {"error": str(exc), "source": spec}
        except Exception as exc:  # noqa: BLE001 - surface, never crash a tool
            return {"error": f"{type(exc).__name__}: {exc}", "source": spec}
        try:
            payload = build(query)
        finally:
            query.store.close()
        if query.snapshot is not None:
            payload["snapshot"] = _snapshot_block(query.snapshot)
        return payload

    # -- registration ------------------------------------------------

    def register(self, mcp: "FastMCP") -> None:
        if not self.sources:
            return

        @mcp.tool(annotations=_READ_ONLY)
        def molmcp_find_capability(
            task: str, source: str | None = None, max_results: int = 8
        ) -> dict:
            """Discover what a codebase provides for a task.

            Primary discovery tool. Searches indexed symbols and returns
            ranked matches, each with signature, summary, usage
            examples, tests, and callers — so an agent resolves a
            capability from real code instead of guessing names.

            Args:
                task: Natural-language description of what you need.
                source: Configured source to search; omit for the default.
                max_results: Max ranked matches (1-25).
            """
            limit = _clamp(max_results, 1, 25)
            return self._with_query(
                source,
                lambda q: EvidenceBuilder(q).find_capability(task, limit),
            )

        @mcp.tool(annotations=_READ_ONLY)
        def molmcp_search_symbols(
            query: str,
            source: str | None = None,
            kind: str | None = None,
            max_results: int = 30,
        ) -> dict:
            """Search indexed symbols by name, qualname, or summary.

            Args:
                query: Free-text search string.
                source: Configured source to search; omit for the default.
                kind: Optional node-kind filter (e.g. ``class``,
                    ``function``, ``method``, ``test``).
                max_results: Max results (1-100).
            """
            limit = _clamp(max_results, 1, 100)

            def build(q: DiscoveryQuery) -> dict:
                results = q.search(query, kind=kind, limit=limit)
                return {
                    "query": query,
                    "kind": kind,
                    "result_count": len(results),
                    "results": [node_brief(n) for n in results],
                }

            return self._with_query(source, build)

        @mcp.tool(annotations=_READ_ONLY)
        def molmcp_describe_symbol(
            qualname: str,
            source: str | None = None,
            include_source: bool = False,
        ) -> dict:
            """Return full detail for one symbol.

            Args:
                qualname: Fully-qualified symbol name (from a prior
                    search/outline result — do not guess).
                source: Configured source; omit for the default.
                include_source: Include the symbol's source code.
            """

            def build(q: DiscoveryQuery) -> dict:
                root = q.snapshot.root_dir if q.snapshot else None
                detail = EvidenceBuilder(q).describe(
                    qualname, include_source, root
                )
                if detail is None:
                    return {
                        "error": f"symbol not found: {qualname}",
                        "hint": "use molmcp_search_symbols or molmcp_outline",
                    }
                return {"symbol": detail}

            return self._with_query(source, build)

        @mcp.tool(annotations=_READ_ONLY)
        def molmcp_relations(
            qualname: str,
            relation: str,
            source: str | None = None,
            depth: int = 1,
            max_results: int = 40,
        ) -> dict:
            """Walk the code graph from a symbol along one relation.

            Args:
                qualname: Fully-qualified symbol name.
                relation: One of ``callers``, ``callees``,
                    ``implementers``, ``subclasses``, ``references``,
                    ``examples``, ``tests``, ``impact``.
                source: Configured source; omit for the default.
                depth: Hops for ``impact`` (1-4); ignored otherwise.
                max_results: Max related nodes (1-100).
            """
            if relation not in _RELATIONS:
                return {
                    "error": f"unknown relation {relation!r}",
                    "valid_relations": list(_RELATIONS),
                }
            limit = _clamp(max_results, 1, 100)
            hops = _clamp(depth, 1, 4)

            def build(q: DiscoveryQuery) -> dict:
                if relation in ("implementers", "subclasses"):
                    nodes = q.implementers(qualname, limit)
                elif relation == "impact":
                    nodes = q.impact(qualname, depth=hops, limit=limit)
                else:
                    nodes = getattr(q, _METHOD[relation])(qualname, limit)
                if relation == "examples":
                    items = [example_view(n) for n in nodes]
                else:
                    items = [node_brief(n) for n in nodes]
                return {
                    "of": qualname,
                    "relation": relation,
                    "result_count": len(items),
                    "results": items,
                }

            return self._with_query(source, build)

        @mcp.tool(annotations=_READ_ONLY)
        def molmcp_outline(
            source: str | None = None, path: str | None = None
        ) -> dict:
            """Map a source's packages/modules to their symbols.

            The "where do I look" tool — call this first to see what a
            codebase contains before drilling in.

            Args:
                source: Configured source; omit for the default.
                path: Optional file or directory prefix to narrow to.
            """

            def build(q: DiscoveryQuery) -> dict:
                outline = q.outline(path=path)
                modules = outline["modules"]
                truncated = len(modules) > _MAX_OUTLINE_MODULES
                if truncated:
                    outline["modules"] = modules[:_MAX_OUTLINE_MODULES]
                outline["truncated"] = truncated
                return outline

            return self._with_query(source, build)

        @mcp.tool(annotations=_READ_ONLY)
        def molmcp_refresh(source: str | None = None) -> dict:
            """Force a fresh re-index of a source.

            Indexing is lazy and automatic; use this only to rebuild a
            source's graph on demand. Reads source and writes only to
            molmcp's own cache.

            Args:
                source: Configured source; omit for the default.
            """
            spec, err = self._select_source(source)
            if err is not None:
                return err
            try:
                result = self.engine().index(spec, force=True)
            except SourceError as exc:
                return {"error": str(exc), "source": spec}
            except Exception as exc:  # noqa: BLE001
                return {"error": f"{type(exc).__name__}: {exc}", "source": spec}
            return {
                "refreshed": True,
                "indexed": {
                    "files": result.file_count,
                    "nodes": result.node_count,
                    "edges": result.edge_count,
                },
                "snapshot": _snapshot_block(result.snapshot),
            }


_METHOD = {
    "callers": "callers",
    "callees": "callees",
    "references": "references",
    "examples": "examples_of",
    "tests": "tests_of",
}
