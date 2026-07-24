"""Thin FastMCP adapter — OKF-style knowledge pages for context injection."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from mcp.types import ToolAnnotations

from .collection import MAX_CONTEXT_BUDGET, CollectionIndex
from .collection.browse import (
    compose_context,
    open_ref,
    outline_source,
    packages_catalog,
    search_scoped,
)
from .guide import build_routing_guide

if TYPE_CHECKING:
    from fastmcp import FastMCP

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


class MolCraftsContextProvider:
    """Register hierarchical discovery tools (packages → outline → open → compose).

    Codegraph is the index; tools inject markdown knowledge pages into context.
    Legacy describe/usage/guide/explore remain as thin aliases for one minor.
    """

    name = "molcrafts"

    def __init__(
        self,
        collection: CollectionIndex,
        runtime_status: Mapping[str, Any] | None = None,
    ) -> None:
        self.collection = collection
        self.runtime_status = runtime_status if runtime_status is not None else {}

    def register(self, mcp: FastMCP) -> None:
        collection = self.collection

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_info(workspace: str | None = None) -> dict[str, Any]:
            """Ops/health view of sources and registry (not the main discovery path)."""
            payload = collection.info()
            configured = payload.get("workspace")
            if (
                workspace is not None
                and configured is not None
                and workspace != configured
            ):
                payload["ok"] = False
                payload["code"] = "WORKSPACE_NOT_CONFIGURED"
                payload["error"] = "workspace_not_configured"
                payload["requested_workspace"] = workspace
            else:
                payload["ok"] = True
                payload["code"] = None
                payload["error"] = None
            payload["runtime"] = dict(self.runtime_status)
            return payload

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_packages() -> dict[str, Any]:
            """L0 directory page: every package + summary for context injection.

            Read the markdown (or data.packages[].summary) and choose sources
            yourself — this is a catalog, not a ranking.
            """
            return packages_catalog(collection)

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_outline(
            source: str,
            path: str | None = None,
            top_symbols_limit: int = 15,
        ) -> dict[str, Any]:
            """L1 module directory for one source (optional path prefix).

            Args:
                source: Name from molcrafts_packages.
                path: Optional path/module prefix to narrow the tree.
                top_symbols_limit: Max sample symbols per module in the page.
            """
            return outline_source(
                collection,
                source,
                path=path,
                top_symbols_limit=top_symbols_limit,
            )

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_open(
            ref: str,
            include_source: bool = False,
        ) -> dict[str, Any]:
            """L2 symbol page: signature, doc, examples, tests (inject before coding).

            Miss → ok=false / SYMBOL_NOT_FOUND. Empty examples are honest zeros.
            """
            return open_ref(collection, ref, include_source=include_source)

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_compose(
            task: str | None = None,
            refs: list[str] | None = None,
            sources: list[str] | None = None,
            budget_chars: int = 16_000,
        ) -> dict[str, Any]:
            """Bind packages + suggest + explore/open pages into one budgeted pack."""
            budget = min(max(budget_chars, 1), MAX_CONTEXT_BUDGET)
            return compose_context(
                collection,
                task=task,
                refs=refs,
                sources=sources,
                budget_chars=budget,
            )

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_search(
            query: str,
            kinds: list[str] | None = None,
            namespaces: list[str] | None = None,
            sources: list[str] | None = None,
            path: str | None = None,
            limit: int = 20,
            mode: str = "all",
        ) -> dict[str, Any]:
            """Index helper: find refs (prefer after packages/outline, with source=).

            Source symbols are evidence only. executable=true only for Molexp bind.
            """
            return search_scoped(
                collection,
                query,
                kinds=kinds,
                namespaces=namespaces,
                sources=sources,
                path=path,
                limit=limit,
                mode=mode,
            )

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_suggest(task: str) -> dict[str, Any]:
            """Optional shortcut: which package pages to read for *task*."""
            info = collection.info()
            sources = (
                info.get("sources") if isinstance(info.get("sources"), dict) else {}
            )
            try:
                hits = collection.search(task, limit=12)
                hit_dicts = [hit.to_dict() for hit in hits]
            except Exception:
                hit_dicts = []
            guide = build_routing_guide(task, sources=sources, hits=hit_dicts)
            guide["freshness"] = info.get("freshness")
            guide["markdown"] = (
                "# Suggest\n\n"
                + "\n".join(
                    f"- **{c.get('role')}**: prefer {c.get('prefer_packages')} "
                    f"(available={c.get('available')})"
                    for c in (guide.get("checklist") or [])
                    if isinstance(c, dict)
                )
                + "\n"
            )
            return guide

        # ── aliases (one-minor compatibility) ──────────────────────────────

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_guide(task: str) -> dict[str, Any]:
            """Deprecated alias of molcrafts_suggest."""
            return molcrafts_suggest(task)

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_describe(
            ref: str,
            include_source: bool = False,
            include_examples: bool = True,
        ) -> dict[str, Any]:
            """Deprecated alias of molcrafts_open.

            include_examples is ignored; examples are always included.
            """
            _ = include_examples
            return molcrafts_open(ref, include_source=include_source)

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_usage(
            ref: str,
            include_source: bool = False,
        ) -> dict[str, Any]:
            """Deprecated alias of molcrafts_open."""
            page = molcrafts_open(ref, include_source=include_source)
            # Keep old shape fields for callers that expect usage/detail.
            if page.get("ok") and page.get("data"):
                page = {
                    **page,
                    "usage": page["data"].get("usage"),
                    "detail": page["data"].get("detail"),
                }
            return page

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_explore(
            task: str,
            namespaces: list[str] | None = None,
            sources: list[str] | None = None,
            budget_chars: int = 16_000,
        ) -> dict[str, Any]:
            """Deprecated alias of molcrafts_compose(task=…)."""
            _ = namespaces
            return molcrafts_compose(
                task=task, sources=sources, budget_chars=budget_chars
            )

        @mcp.resource(
            "molcrafts://workspace/context",
            name="molcrafts-workspace-context",
            mime_type="application/json",
        )
        def workspace_context() -> str:
            payload = collection.info()
            payload["runtime"] = dict(self.runtime_status)
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)

        @mcp.resource(
            "molcrafts://capability/{namespace}/{name}",
            name="molcrafts-capability",
            mime_type="application/json",
        )
        def capability_resource(namespace: str, name: str) -> str:
            ref = f"@{namespace}/{name}"
            detail = collection.describe(ref)
            if detail is None:
                return json.dumps(
                    {
                        "error": "not_found",
                        "ref": ref,
                        "freshness": "unknown",
                        "provenance": {"type": "registry_lookup"},
                    }
                )
            return json.dumps(detail, ensure_ascii=False, sort_keys=True)

        @mcp.resource(
            "molcrafts://source/{source}/symbol/{symbol}",
            name="molcrafts-source-symbol",
            mime_type="application/json",
        )
        def source_symbol_resource(source: str, symbol: str) -> str:
            ref = unquote(symbol)
            detail = collection.describe(ref, include_source=True)
            if detail is None or detail.get("source_name") != source:
                return json.dumps(
                    {
                        "error": "not_found_or_stale",
                        "source": source,
                        "ref": ref,
                        "freshness": "unknown",
                        "provenance": {"type": "source_symbol_lookup"},
                    }
                )
            return json.dumps(detail, ensure_ascii=False, sort_keys=True)
