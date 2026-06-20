"""Reject tool calls whose ``path``-typed arguments contain traversal sequences."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath, PureWindowsPath

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

logger = logging.getLogger(__name__)

_PATH_KEYS = (
    "path",
    "filepath",
    "file_path",
    "filename",
    "relative_path",
    "rel_path",
    "src",
    "dst",
    "input_file",
    "output_file",
)


def _is_unsafe(value: str) -> bool:
    if "\x00" in value:
        return True
    parts = list(PurePosixPath(value).parts) + list(PureWindowsPath(value).parts)
    if any(p == ".." for p in parts):
        return True
    return False


class PathSafetyMiddleware(Middleware):
    """Block tool calls whose path-shaped arguments look traversy.

    Activates only on a fixed set of common parameter names (``path``,
    ``file_path``, etc.). Tools that take an arbitrary string of unknown
    semantics are unaffected.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        params = context.message
        args = params.arguments or {}
        for key, val in args.items():
            if key in _PATH_KEYS and isinstance(val, str) and _is_unsafe(val):
                logger.warning(
                    "PathSafety rejected call to %s: %s=%r", params.name, key, val
                )
                raise ToolError(f"Refusing path-traversal in argument {key!r}: {val!r}")
        return await call_next(context)
