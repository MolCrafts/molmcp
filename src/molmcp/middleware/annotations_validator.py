"""Startup-time check: every tool must declare ``readOnlyHint`` (or destructiveHint).

This is *not* a request-time middleware — it's a one-shot validation pass
run by ``create_server`` after all providers have registered their tools.
Catching this at server build time gives a clear actionable error to the
provider author instead of silently letting clients auto-approve mutating
tools.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.tools.tool import Tool


class MissingAnnotationsError(RuntimeError):
    """Raised when a registered tool is missing required ToolAnnotations."""


def _iter_tools(mcp: FastMCP):
    """Walk fastmcp's provider tree synchronously and yield each Tool component.

    Uses provider ``_components`` storage directly because the public
    ``list_tools`` API is async and we need to validate at server build
    time (which is synchronous, often called from non-async contexts).
    """
    for provider in getattr(mcp, "providers", []):
        components = getattr(provider, "_components", {})
        for component in components.values():
            if isinstance(component, Tool):
                yield component


def validate_tool_annotations(mcp: FastMCP, *, strict: bool = True) -> list[str]:
    """Check every registered tool exposes ``readOnlyHint`` or ``destructiveHint``.

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
                f"set at least readOnlyHint."
            )
            continue
        read_only = getattr(ann, "readOnlyHint", None)
        destructive = getattr(ann, "destructiveHint", None)
        if read_only is None and destructive is None:
            warnings.append(
                f"Tool {tool.name!r} annotations have neither readOnlyHint "
                f"nor destructiveHint set."
            )
    if warnings and strict:
        raise MissingAnnotationsError(
            "Tool annotation validation failed:\n  - "
            + "\n  - ".join(warnings)
        )
    return warnings
