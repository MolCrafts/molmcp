"""Thin FastMCP adapter for the vNext collection/context API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from mcp.types import ToolAnnotations

from .collection import MAX_CONTEXT_BUDGET, CollectionIndex

if TYPE_CHECKING:
    from fastmcp import FastMCP

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


class MolCraftsContextProvider:
    """Register exactly four task-oriented core tools and context resources."""

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
            """Describe configured MolCrafts sources, registries and index health.

            Args:
                workspace: Optional workspace label for the response. The server
                    only accesses roots configured at startup.
            """
            payload = collection.info()
            configured = payload.get("workspace")
            if (
                workspace is not None
                and configured is not None
                and workspace != configured
            ):
                payload["error"] = "workspace_not_configured"
                payload["requested_workspace"] = workspace
            payload["runtime"] = dict(self.runtime_status)
            return payload

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_search(
            query: str,
            kinds: list[str] | None = None,
            namespaces: list[str] | None = None,
            sources: list[str] | None = None,
            limit: int = 20,
        ) -> dict[str, Any]:
            """Search the full capability registry and every configured source.

            Source symbols are evidence only. Only registry results explicitly
            marked ``executable`` are valid Molexp execution capabilities.
            """
            hits = collection.search(
                query,
                kinds=kinds,
                namespaces=namespaces,
                sources=sources,
                limit=min(max(limit, 1), 100),
            )
            return {
                "query": query,
                "result_count": len(hits),
                "results": [hit.to_dict() for hit in hits],
                "freshness": _hit_freshness(hits),
                "provenance": {
                    "type": "federated_search",
                    "channels": sorted(
                        {channel for hit in hits for channel in hit.matched_channels}
                    ),
                },
            }

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_describe(
            ref: str,
            include_source: bool = False,
            include_examples: bool = True,
        ) -> dict[str, Any]:
            """Describe an exact registry or symbol ref returned by search."""
            detail = collection.describe(
                ref,
                include_source=include_source,
                include_examples=include_examples,
            )
            if detail is None:
                return {
                    "error": "ref_not_found_or_stale",
                    "ref": ref,
                    "hint": "call molcrafts_search and use an exact returned ref",
                    "freshness": "unknown",
                    "provenance": {"type": "exact_ref_lookup"},
                }
            return {"ref": ref, "detail": detail}

        @mcp.tool(annotations=_READ_ONLY)
        def molcrafts_explore(
            task: str,
            namespaces: list[str] | None = None,
            sources: list[str] | None = None,
            budget_chars: int = 16_000,
        ) -> dict[str, Any]:
            """Build one bounded, provenance-rich context pack for a task."""
            budget = min(max(budget_chars, 1), MAX_CONTEXT_BUDGET)
            return collection.explore(
                task,
                namespaces=namespaces,
                sources=sources,
                budget_chars=budget,
            ).to_dict()

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


def _hit_freshness(hits: list[Any]) -> dict[str, Any]:
    values = {hit.freshness for hit in hits}
    if "stale" in values:
        overall = "stale"
    elif "pending" in values:
        overall = "pending"
    elif not values or "unknown" in values:
        overall = "unknown"
    else:
        overall = "fresh"
    return {"overall": overall}
