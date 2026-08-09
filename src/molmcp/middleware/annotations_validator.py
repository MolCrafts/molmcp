"""Startup-time check: every tool must declare ``read_only_hint`` (or destructive).

This is *not* a request-time middleware — it's a one-shot validation pass
run by ``create_plane`` after tools have registered. Catching this at server
build time gives a clear actionable error to the provider author instead of
silently letting clients auto-approve mutating tools.

Field names follow MCP SDK v2 / FastMCP 4 snake_case (wire remains camelCase).
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.tools import Tool


class MissingAnnotationsError(RuntimeError):
    """Raised when a registered tool is missing required ToolAnnotations."""


def _iter_tools(mcp: FastMCP, *, _seen: set[int] | None = None):
    """Walk fastmcp's provider tree synchronously and yield each Tool component.

    Uses provider ``_components`` storage directly because the public
    ``list_tools`` API is async and we need to validate at server build
    time (which is synchronous, often called from non-async contexts).
    """
    seen = _seen if _seen is not None else set()
    if id(mcp) in seen:
        return
    seen.add(id(mcp))

    for provider in getattr(mcp, "providers", []):
        components = getattr(provider, "_components", {})
        for component in components.values():
            if isinstance(component, Tool):
                yield component

        # Legacy FastMCP.mount adapters (if any); multi-plane servers register
        # tools on the root only — walk children so validation still covers them.
        inner = getattr(provider, "_inner", None)
        child = getattr(inner, "server", None)
        if isinstance(child, FastMCP):
            yield from _iter_tools(child, _seen=seen)


def validate_tool_annotations(mcp: FastMCP, *, strict: bool = True) -> list[str]:
    """Check every registered tool exposes ``read_only_hint`` or ``destructive_hint``.

    Args:
        mcp: The server to check.
        strict: If True, raise MissingAnnotationsError on the first violation
            rather than just collecting warnings.

    Returns:
        List of human-readable warnings about tools missing annotations.
        Empty list means all tools are properly annotated.
    """
    warnings: list[str] = []
    for tool in _iter_tools(mcp):
        ann = getattr(tool, "annotations", None)
        if ann is None:
            warnings.append(
                f"Tool {tool.name!r} has no ToolAnnotations — "
                f"set at least read_only_hint."
            )
            continue
        # MCP SDK v2 / FastMCP 4: snake_case fields (2026-07-28 era).
        read_only = getattr(ann, "read_only_hint", None)
        destructive = getattr(ann, "destructive_hint", None)
        if read_only is None and destructive is None:
            warnings.append(
                f"Tool {tool.name!r} annotations have neither read_only_hint "
                f"nor destructive_hint set."
            )
    if warnings and strict:
        raise MissingAnnotationsError(
            "Tool annotation validation failed:\n  - " + "\n  - ".join(warnings)
        )
    return warnings
