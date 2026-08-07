"""Thin FastMCP adapter — OKF-style knowledge pages for the molcrafts plane."""

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
from .source_scope import (
    deny_source,
    filter_package_cards,
    get_env_source_allowlist,
    intersect_sources,
    ref_source,
    source_allowed,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


class MolCraftsContextProvider:
    """Register hierarchical discovery tools on the **molcrafts** plane.

    Tool names are bare (``packages``, ``open``, …). The MCP server name is
    ``molcrafts``, so clients see ``molcrafts__packages`` — never a mega
    ``molmcp__molcrafts_*`` prefix stack.
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
        # Snapshot at register time; restart process to pick up env changes.
        scope = get_env_source_allowlist()

        def _scoped_sources(requested: list[str] | None) -> list[str] | None:
            return intersect_sources(requested, scope)

        @mcp.tool(annotations=_READ_ONLY)
        def info(workspace: str | None = None) -> dict[str, Any]:
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
            if scope is not None:
                src = payload.get("sources")
                if isinstance(src, dict):
                    payload["sources"] = {
                        k: v for k, v in src.items() if source_allowed(str(k), scope)
                    }
                payload["source_scope"] = sorted(scope)
            return payload

        @mcp.tool(annotations=_READ_ONLY)
        def packages() -> dict[str, Any]:
            """L0 directory page: every package + summary for context injection.

            Read the markdown (or data.packages[].summary) and choose sources
            yourself — this is a catalog, not a ranking.

            When ``MOLMCP_SOURCES`` is set, only those packages appear.
            """
            catalog = packages_catalog(collection)
            if scope is None:
                return catalog
            data = catalog.get("data") if isinstance(catalog.get("data"), dict) else {}
            cards = filter_package_cards(data.get("packages") or [], scope)
            names = [c.get("name") for c in cards if isinstance(c.get("name"), str)]
            md_lines = [
                "# Packages (scoped)",
                "",
                f"Active knowledge scope: {', '.join(sorted(scope))}",
                "",
            ]
            for card in cards:
                name = card.get("name")
                summary = card.get("summary") or ""
                md_lines.append(f"- **{name}**: {summary}")
            return {
                **catalog,
                "markdown": "\n".join(md_lines) + "\n",
                "data": {
                    **data,
                    "packages": cards,
                    "source_scope": sorted(scope),
                    "package_names": names,
                },
            }

        @mcp.tool(annotations=_READ_ONLY)
        def outline(
            source: str,
            path: str | None = None,
            top_symbols_limit: int = 15,
        ) -> dict[str, Any]:
            """L1 module directory for one source (optional path prefix).

            Args:
                source: Name from packages.
                path: Optional path/module prefix to narrow the tree.
                top_symbols_limit: Max sample symbols per module in the page.
            """
            if not source_allowed(source, scope):
                return deny_source(source, scope)
            return outline_source(
                collection,
                source,
                path=path,
                top_symbols_limit=top_symbols_limit,
            )

        @mcp.tool(annotations=_READ_ONLY)
        def open(
            ref: str,
            include_source: bool = False,
        ) -> dict[str, Any]:
            """L2 symbol page: signature, doc, examples, tests (inject before coding).

            Miss → ok=false / SYMBOL_NOT_FOUND. Empty examples are honest zeros.
            """
            src = ref_source(ref)
            if src is not None and not source_allowed(src, scope):
                return deny_source(src, scope)
            return open_ref(collection, ref, include_source=include_source)

        @mcp.tool(annotations=_READ_ONLY)
        def compose(
            task: str | None = None,
            refs: list[str] | None = None,
            sources: list[str] | None = None,
            budget_chars: int = 16_000,
        ) -> dict[str, Any]:
            """Bind packages + suggest + explore/open pages into one budgeted pack.

            ``sources`` is intersected with ``MOLMCP_SOURCES`` when set.
            """
            budget = min(max(budget_chars, 1), MAX_CONTEXT_BUDGET)
            scoped = _scoped_sources(sources)
            if scope is not None and scoped is not None and len(scoped) == 0:
                return deny_source(",".join(sources or []), scope)
            return compose_context(
                collection,
                task=task,
                refs=refs,
                sources=scoped,
                budget_chars=budget,
            )

        @mcp.tool(annotations=_READ_ONLY)
        def search(
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
            ``sources`` is intersected with ``MOLMCP_SOURCES`` when set.
            """
            scoped = _scoped_sources(sources)
            if scope is not None and scoped is not None and len(scoped) == 0:
                return deny_source(",".join(sources or []), scope)
            return search_scoped(
                collection,
                query,
                kinds=kinds,
                namespaces=namespaces,
                sources=scoped,
                path=path,
                limit=limit,
                mode=mode,
            )

        @mcp.tool(annotations=_READ_ONLY)
        def suggest(task: str) -> dict[str, Any]:
            """Optional shortcut: which package pages to read for *task*."""
            info_payload = collection.info()
            sources_map = (
                info_payload.get("sources")
                if isinstance(info_payload.get("sources"), dict)
                else {}
            )
            if scope is not None:
                sources_map = {
                    k: v
                    for k, v in sources_map.items()
                    if source_allowed(str(k), scope)
                }
            try:
                hits = collection.search(task, limit=12)
                hit_dicts = [hit.to_dict() for hit in hits]
                if scope is not None:
                    hit_dicts = [
                        h
                        for h in hit_dicts
                        if source_allowed(
                            str(h.get("source") or h.get("source_name") or ""),
                            scope,
                        )
                        or source_allowed(
                            str(h.get("ref") or "").split(".", 1)[0], scope
                        )
                    ]
            except Exception:
                hit_dicts = []
            guide = build_routing_guide(task, sources=sources_map, hits=hit_dicts)
            if scope is not None:
                guide["source_scope"] = sorted(scope)
                preferred = [
                    p
                    for p in (guide.get("preferred_packages") or [])
                    if isinstance(p, str) and source_allowed(p, scope)
                ]
                guide["preferred_packages"] = preferred
            guide["freshness"] = info_payload.get("freshness")
            guide["markdown"] = (
                "# Suggest\n\n"
                + (
                    f"_Scope: {', '.join(sorted(scope))}_\n\n"
                    if scope is not None
                    else ""
                )
                + "\n".join(
                    f"- **{c.get('role')}**: prefer {c.get('prefer_packages')} "
                    f"(available={c.get('available')})"
                    for c in (guide.get("checklist") or [])
                    if isinstance(c, dict)
                )
                + "\n"
            )
            return guide

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
